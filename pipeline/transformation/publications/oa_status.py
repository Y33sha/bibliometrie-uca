"""Phase `oa_status` : statut d'accès ouvert des publications (`publications.oa_status`), lu dans Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour le statut OA. Une publication est marquée vérifiée seulement si Unpaywall a répondu ; quand Unpaywall est indisponible, elle attend le run suivant. Le statut reçu écrase l'existant, à deux exceptions près : 'diamond' n'est pas remplacé par 'gold' ; 'embargoed' n'est pas remplacé par 'closed' ou 'unknown', l'embargo étant connu côté HAL quand Unpaywall voit seulement un fichier inaccessible. Un statut plus ouvert (green+) l'emporte dans les deux cas.

Implémentation async : `httpx2.AsyncClient` partagé + `asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
from sqlalchemy import Connection

from domain.publications.metadata import decide_oa_status
from pipeline.ingestion.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.node_runner import NodePhase
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import (
    BRANCHE,
    DERNIERE_BRANCHE,
    accord,
    etape,
    forme,
    rien_a_faire,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression
from pipeline.transformation.publications.oa_status_queries import OaStatusQueries

type OaStatusFetcher = Callable[[httpx2.AsyncClient, str], Awaitable[LookupOutcome[str]]]
"""Signature : `(client, doi) → statut OA mappé, NOT_FOUND ou UNAVAILABLE`."""

# Constantes opérationnelles.
BATCH_SIZE = 50
MAX_CONCURRENT = 5


@dataclass(frozen=True)
class OaStatusPhase:
    """Vérifie sur Unpaywall le statut OA des publications à DOI.

    `staleness_days` lit le délai, en jours, au-delà duquel une publication vérifiée l'est de nouveau. `max_per_run` lit le plafond de DOI vérifiés par run, `None` valant illimité.
    """

    queries: OaStatusQueries
    fetcher: OaStatusFetcher
    staleness_days: Callable[[Connection], int]
    max_per_run: Callable[[Connection], int | None]
    max_concurrent: int = MAX_CONCURRENT

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Vérifie les publications dans une seule transaction."""
        metrics = PhaseMetrics()
        with ctx.open_tx() as conn:
            metrics.merge(
                asyncio.run(
                    _verifier(
                        conn,
                        self.queries,
                        ctx.logger,
                        fetcher=self.fetcher,
                        staleness_days=self.staleness_days(conn),
                        max_per_run=self.max_per_run(conn),
                        max_concurrent=self.max_concurrent,
                    )
                )
            )
        return metrics


async def _verifier(
    conn: Connection,
    queries: OaStatusQueries,
    logger: logging.Logger,
    *,
    fetcher: OaStatusFetcher,
    staleness_days: int,
    max_per_run: int | None,
    max_concurrent: int,
) -> PhaseMetrics:
    """Interroge Unpaywall pour les publications à DOI (re)vérifier et met à jour leur `oa_status`, puis rend les métriques du run."""
    metrics = PhaseMetrics()
    pubs = queries.fetch_publications_with_doi(
        conn, limit=max_per_run, staleness_days=staleness_days
    )
    total = len(pubs)
    stale_total = queries.count_stale_publications(conn, staleness_days=staleness_days)
    before_dist = queries.count_publications_by_oa_status(conn)

    progress = {"updated": 0, "skipped": 0, "not_found": 0, "unavailable": 0}

    def _result() -> PhaseMetrics:
        # Indicateurs : synthèse du run (backlog, vérifiées, ventilation) puis répartition des publications par statut OA avec le delta du run (avant → après).
        metrics.add(
            total=total,
            updated=progress["updated"],
            unchanged=progress["skipped"],
            not_found=progress["not_found"],
            errors=progress["unavailable"],
        )
        after_dist = queries.count_publications_by_oa_status(conn)
        statuses = sorted(
            set(before_dist) | set(after_dist),
            key=lambda s: after_dist.get(s, 0),
            reverse=True,
        )
        metrics.details["summary"] = {
            "stale": stale_total,
            "checked": total,
            "updated": progress["updated"],
            "unchanged": progress["skipped"],
            "not_found": progress["not_found"],
            "unavailable": progress["unavailable"],
        }
        metrics.details["table"] = {
            "rows": [
                {
                    "key": s,
                    "count": after_dist.get(s, 0),
                    "delta": after_dist.get(s, 0) - before_dist.get(s, 0),
                }
                for s in statuses
            ]
        }
        # Chaque ligne de la sous-étape porte son décompte : une ligne de clôture les répéterait.
        metrics.resume = ""
        return metrics

    etape(logger, "Vérification du statut open access sur Unpaywall")
    if not total:
        rien_a_faire(logger)
        return _result()

    logger.info(
        "%s%s %s ou %s depuis plus de %s",
        BRANCHE,
        accord(stale_total, "publication"),
        forme(stale_total, "jamais vérifiée"),
        forme(stale_total, "vérifiée"),
        accord(staleness_days, "jour"),
    )
    if max_per_run and max_per_run < stale_total:
        reportees = stale_total - total
        logger.info(
            "%splafond de %s par run ⇒ %s %s au prochain",
            BRANCHE,
            max_per_run,
            reportees,
            forme(reportees, "reportée"),
        )

    sem = asyncio.Semaphore(max_concurrent)
    # La `Connection` SA sync n'est pas thread-safe ; les writes concurrents d'un paquet passent par `to_thread` sous ce lock (le commit, lui, se fait à la frontière de paquet, hors concurrence).
    db_lock = asyncio.Lock()

    async with httpx2.AsyncClient() as client:

        async def process_one(
            pub_id: int, doi: str, current_status: str | None, has_open_deposit: bool
        ) -> None:
            async with sem:
                status = await fetcher(client, doi)

            # Unpaywall indisponible : rien n'est écrit, la publication reste dans la file.
            if isinstance(status, Unavailable):
                progress["unavailable"] += 1
                return
            # `new_status` non None = on écrit un nouveau statut ; sinon on pose seulement
            # `unpaywall_checked_at`, que la publication soit absente d'Unpaywall ou que son
            # statut y soit inchangé — dans les deux cas elle sort de la file jusqu'à péremption.
            new_status: str | None = None
            if isinstance(status, NotFound):
                progress["not_found"] += 1
            else:
                new_status = decide_oa_status(current_status, status, has_open_deposit)
                if new_status is None:
                    progress["skipped"] += 1
                else:
                    progress["updated"] += 1

            async with db_lock:
                if new_status is not None:
                    await asyncio.to_thread(queries.update_oa_status, conn, pub_id, new_status)
                else:
                    await asyncio.to_thread(queries.mark_unpaywall_checked, conn, pub_id)

        # Traitement par paquets : chaque paquet part en concurrence (débit borné par `sem`) puis est committé.
        with progression(total, BRANCHE.rstrip(), logger) as avancement:
            for start in range(0, total, BATCH_SIZE):
                chunk = pubs[start : start + BATCH_SIZE]
                await asyncio.gather(*(process_one(*pub) for pub in chunk))
                await asyncio.to_thread(conn.commit)
                avancement.avance(len(chunk))

    logger.info(
        "%s%s %s, %s %s, %s non %s, %s %s faute de réponse d'Unpaywall",
        DERNIERE_BRANCHE,
        progress["updated"],
        forme(progress["updated"], "mise à jour", "mises à jour"),
        progress["skipped"],
        forme(progress["skipped"], "inchangée"),
        progress["not_found"],
        forme(progress["not_found"], "trouvée"),
        progress["unavailable"],
        forme(progress["unavailable"], "reportée"),
    )

    return _result()


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Enrichissement de `publications.oa_status`, une publication à la fois, via Unpaywall.

    Le délai de péremption et le plafond par run bornent la phase : le retard des publications jamais vérifiées s'écoule d'un run à l'autre. La phase passe par l'accès à Unpaywall, qui exige l'adresse électronique du polite pool.
    """

    from pipeline.ingestion.complements.unpaywall import fetch_oa_status
    from pipeline.ingestion.http.api_params import API_BASE_URLS
    from pipeline.runtime.config import (
        get_polite_pool_email_optional,
        get_unpaywall_max_per_run,
        get_unpaywall_recheck_after_days,
    )
    from pipeline.transformation.publications.oa_status_queries import OaStatusQueries

    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email)

    return NodePhase(
        "oa_status.verify_unpaywall",
        OaStatusPhase(
            OaStatusQueries(),
            fetcher,
            staleness_days=get_unpaywall_recheck_after_days,
            max_per_run=get_unpaywall_max_per_run,
        ),
    )
