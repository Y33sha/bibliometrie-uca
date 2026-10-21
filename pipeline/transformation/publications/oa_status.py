"""Phase `oa_status` : verdicts d'Unpaywall sur les DOI des publications (`sources.unpaywall`), et statut open access qui en découle (`publications.oa_status`).

La phase interroge Unpaywall pour les DOI jamais vérifiés ou périmés, et écrit chaque verdict. Un DOI absent d'Unpaywall reçoit un verdict nul. Quand Unpaywall est indisponible, le DOI attend le run suivant. Le statut des publications de ces DOI se recalcule ensuite par `publication_oa_status`, à partir de leurs notices et du verdict.

Le délai de péremption et le plafond par run bornent la phase : le retard des DOI jamais vérifiés s'écoule d'un run à l'autre. La phase passe par l'accès à Unpaywall, qui exige l'adresse du polite pool.

Implémentation async : `httpx2.AsyncClient` partagé + `asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
from sqlalchemy import Connection

from domain.config import ConfigKey
from domain.publications.metadata import publication_oa_status
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import get_polite_pool_email_optional
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.complements.unpaywall import fetch_oa_status
from pipeline.runtime.config import cap, delay
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.task_runner import SingleTaskPhase
from pipeline.transformation.publications.oa_status_queries import OaStatusQueries

type OaStatusFetcher = Callable[[httpx2.AsyncClient, str], Awaitable[LookupOutcome[str]]]
"""Signature : `(client, doi) → statut OA mappé, NOT_FOUND ou UNAVAILABLE`."""

# Constantes opérationnelles.
BATCH_SIZE = 50
MAX_CONCURRENT = 5


@dataclass(frozen=True)
class OaStatusPhase:
    """Vérifie sur Unpaywall le statut OA des publications à DOI.

    `staleness_days` lit le délai, en jours, au-delà duquel un DOI vérifié l'est de nouveau. `max_per_run` lit le plafond de DOI vérifiés par run, `None` valant illimité.
    """

    queries: OaStatusQueries
    fetcher: OaStatusFetcher
    staleness_days: Callable[[Connection], int]
    max_per_run: Callable[[Connection], int | None]
    max_concurrent: int = MAX_CONCURRENT

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Vérifie les DOI dans une seule transaction, avec un commit par paquet."""
        metrics = PhaseMetrics()
        with ctx.open_tx() as conn:
            metrics.merge(
                asyncio.run(
                    _check(
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


async def _check(
    conn: Connection,
    queries: OaStatusQueries,
    logger: logging.Logger,
    *,
    fetcher: OaStatusFetcher,
    staleness_days: int,
    max_per_run: int | None,
    max_concurrent: int,
) -> PhaseMetrics:
    """Interroge Unpaywall pour les DOI à vérifier, écrit les verdicts, recalcule le statut OA des publications de ces DOI, puis rend les métriques du run."""
    metrics = PhaseMetrics()
    dois = queries.fetch_dois_to_check(conn, limit=max_per_run, staleness_days=staleness_days)
    total = len(dois)
    stale_total = queries.count_dois_to_check(conn, staleness_days=staleness_days)
    before_dist = queries.count_publications_by_oa_status(conn)

    progress = {"new": 0, "updated": 0, "unchanged": 0, "not_found": 0, "unavailable": 0}

    def _result() -> PhaseMetrics:
        # Indicateurs : verdicts du run (nouveaux, modifiés, inchangés, non trouvés), puis répartition des publications par statut OA avec le delta du run (avant → après).
        metrics.add(
            seen=total,
            new=progress["new"],
            updated=progress["updated"],
            unchanged=progress["unchanged"],
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
            "new": progress["new"],
            "updated": progress["updated"],
            "unchanged": progress["unchanged"],
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
        return metrics

    step(logger, "Vérification du statut open access sur Unpaywall")
    if not total:
        nothing_to_do(logger)
        return _result()

    logger.info(
        "%s%s %s ou %s depuis plus de %s",
        BRANCH,
        quantity(stale_total, "DOI", "DOI"),
        inflect(stale_total, "jamais vérifié"),
        inflect(stale_total, "vérifié"),
        quantity(staleness_days, "jour"),
    )
    if max_per_run and max_per_run < stale_total:
        deferred = stale_total - total
        logger.info(
            "%splafond de %s par run ⇒ %s %s au prochain",
            BRANCH,
            max_per_run,
            deferred,
            inflect(deferred, "reporté"),
        )

    sem = asyncio.Semaphore(max_concurrent)

    async with httpx2.AsyncClient(verify=tls_context()) as client:

        async def fetch(doi: str) -> tuple[str, LookupOutcome[str]]:
            async with sem:
                return doi, await fetcher(client, doi)

        # Par paquets : les requêtes d'un paquet partent en concurrence (débit borné par `sem`), puis ses écritures sont committées.
        with track_progress(total, BRANCH.rstrip(), logger) as bar:
            for start in range(0, total, BATCH_SIZE):
                chunk = dois[start : start + BATCH_SIZE]
                verdicts: list[tuple[str, str | None]] = []
                for doi, outcome in await asyncio.gather(*(fetch(doi) for doi in chunk)):
                    # Unpaywall indisponible : rien n'est écrit, le DOI reste dans la file.
                    if isinstance(outcome, Unavailable):
                        progress["unavailable"] += 1
                    elif isinstance(outcome, NotFound):
                        verdicts.append((doi, None))
                    else:
                        verdicts.append((doi, outcome))
                await asyncio.to_thread(_apply_verdicts, conn, queries, verdicts, progress)
                await asyncio.to_thread(conn.commit)
                bar.advance(len(chunk))

    summary = [
        quantity(progress["new"], "nouveau", "nouveaux"),
        quantity(progress["updated"], "modifié"),
        quantity(progress["unchanged"], "inchangé"),
        quantity(progress["not_found"], "non trouvé", "non trouvés"),
    ]
    if progress["unavailable"]:
        summary.append(quantity(progress["unavailable"], "reporté"))
    logger.info("%s%s", LAST_BRANCH, ", ".join(summary))

    return _result()


def _apply_verdicts(
    conn: Connection,
    queries: OaStatusQueries,
    verdicts: list[tuple[str, str | None]],
    progress: dict[str, int],
) -> None:
    """Classe les verdicts face à ceux en table, les écrit, puis recalcule le statut OA des publications de ces DOI (`publication_oa_status`)."""
    by_doi = dict(verdicts)
    stored = queries.fetch_verdicts(conn, list(by_doi))
    for doi, status in verdicts:
        if status is None:
            progress["not_found"] += 1
        elif doi not in stored:
            progress["new"] += 1
        elif stored[doi] != status:
            progress["updated"] += 1
        else:
            progress["unchanged"] += 1
    queries.record_verdicts(conn, verdicts)
    for publication in queries.fetch_oa_inputs(conn, list(by_doi)):
        status = publication_oa_status(publication.signals, by_doi.get(publication.doi))
        if status != publication.oa_status:
            queries.update_oa_status(conn, publication.id, status)


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email)

    return SingleTaskPhase(
        "oa_status.verify_unpaywall",
        OaStatusPhase(
            OaStatusQueries(),
            fetcher,
            staleness_days=lambda conn: delay(conn, ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS),
            max_per_run=lambda conn: cap(conn, ConfigKey.UNPAYWALL_MAX_PER_RUN),
        ),
    )
