"""
Phase pipeline `oa_status` — enrichit `publications.oa_status` via Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour le statut OA. Le statut reçu écrase l'existant, à deux exceptions près : 'diamond' n'est pas remplacé par 'gold' ; 'embargoed' n'est pas remplacé par 'closed' ou 'unknown', l'embargo étant connu côté HAL quand Unpaywall voit seulement un fichier inaccessible. Un statut plus ouvert (green+) l'emporte dans les deux cas.

Implémentation async : `httpx2.AsyncClient` partagé + `asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx2
from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.ports.pipeline.oa_status import OaStatusQueries
from domain.publications.metadata import decide_oa_status

type OaStatusFetcher = Callable[[httpx2.AsyncClient, str], Awaitable[str | None]]
"""Signature : `(client, doi) → statut OA mappé (str) | None`."""

# Constantes opérationnelles.
BATCH_SIZE = 50
MAX_CONCURRENT = 5
STALENESS_DAYS = 15
"""Au-delà, un statut OA est re-vérifié."""


async def run(
    conn: Connection,
    queries: OaStatusQueries,
    logger: logging.Logger,
    *,
    fetcher: OaStatusFetcher,
    max_per_run: int | None,
    max_concurrent: int = MAX_CONCURRENT,
) -> PhaseMetrics:
    """Interroge Unpaywall pour les publications à DOI (re)vérifier et met à jour leur `oa_status`, puis rend les métriques du run.

    `max_per_run` borne le nombre de DOI vérifiés, `None` valant illimité.
    """
    metrics = PhaseMetrics()
    pubs = queries.fetch_publications_with_doi(
        conn, limit=max_per_run, staleness_days=STALENESS_DAYS
    )
    total = len(pubs)
    stale_total = queries.count_stale_publications(conn, staleness_days=STALENESS_DAYS)
    before_dist = queries.count_publications_by_oa_status(conn)

    progress = {"updated": 0, "skipped": 0, "not_found": 0}

    def _result() -> PhaseMetrics:
        # Indicateurs : synthèse du run (backlog, vérifiées, ventilation) puis répartition des publications par statut OA avec le delta du run (avant → après).
        metrics.add(
            total=total,
            updated=progress["updated"],
            unchanged=progress["skipped"],
            not_found=progress["not_found"],
            stale=stale_total,
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
        logger.info("%sRien à faire", DERNIERE_BRANCHE)
        return _result()

    logger.info(
        "%s%s %s ou %s depuis plus de %s",
        BRANCHE,
        accord(stale_total, "publication"),
        forme(stale_total, "jamais vérifiée"),
        forme(stale_total, "vérifiée"),
        accord(STALENESS_DAYS, "jour"),
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

            # `new_status` non None = on écrit un nouveau statut ; sinon on pose seulement
            # `unpaywall_checked_at`, que la publication soit absente d'Unpaywall ou que son
            # statut y soit inchangé — dans les deux cas elle sort de la file jusqu'à péremption.
            new_status: str | None = None
            if status is None:
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
        "%s%s %s, %s %s, %s non %s",
        DERNIERE_BRANCHE,
        progress["updated"],
        forme(progress["updated"], "mise à jour", "mises à jour"),
        progress["skipped"],
        forme(progress["skipped"], "inchangée"),
        progress["not_found"],
        forme(progress["not_found"], "trouvée"),
    )

    return _result()
