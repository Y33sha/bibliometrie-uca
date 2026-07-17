"""
Phase pipeline `oa_status` — enrichit `publications.oa_status` via Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour le statut OA. Écrase les valeurs existantes, SAUF : (1) ne remplace jamais 'diamond' par 'gold' (Unpaywall ne connaît pas le diamond OA) ; (2) ne rétrograde jamais 'embargoed' vers 'closed'/'unknown' (l'embargo est connu côté HAL, Unpaywall voit juste le fichier non encore accessible) — un statut plus ouvert (green+) écrase bien.

Implémentation async : `httpx.AsyncClient` partagé + `asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.oa_status import OaStatusQueries
from application.ports.repositories.publication_repository import PublicationRepository
from domain.publications.metadata import decide_oa_status

type OaStatusFetcher = Callable[[httpx.AsyncClient, str], Awaitable[str | None]]
"""Signature : `(client, doi) → statut OA mappé (str) | None`."""

# Constantes opérationnelles.
BATCH_SIZE = 50
MAX_CONCURRENT = 5
MAX_PER_RUN = 10_000
"""Nombre maximum de DOI vérifiés par run : lisse la charge, le backlog des jamais-vérifiés s'écoulant sur plusieurs runs au lieu d'un pic."""
STALENESS_DAYS = 15
"""Au-delà, un statut OA est re-vérifié."""


async def run(
    conn: Connection,
    queries: OaStatusQueries,
    logger: logging.Logger,
    *,
    publication_repo: PublicationRepository,
    fetcher: OaStatusFetcher,
    max_concurrent: int = MAX_CONCURRENT,
) -> PhaseMetrics:
    """Interroge Unpaywall pour les publications à DOI (re)vérifier et met à jour leur `oa_status`, puis rend les métriques du run."""
    logger.info("▶ enrich_oa_status")
    t0 = time.perf_counter()
    metrics = PhaseMetrics()
    pubs = queries.fetch_publications_with_doi(
        conn, limit=MAX_PER_RUN, staleness_days=STALENESS_DAYS
    )
    total = len(pubs)
    stale_total = queries.count_stale_publications(conn, staleness_days=STALENESS_DAYS)
    before_dist = queries.count_publications_by_oa_status(conn)
    logger.info(
        f"{total} publications à (re)vérifier sur Unpaywall "
        f"(max {MAX_PER_RUN}, staleness {STALENESS_DAYS}j) — {stale_total} stale au total"
    )

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
        logger.info(
            "✓ enrich_oa_status terminé en %.1fs — %s",
            time.perf_counter() - t0,
            metrics.as_summary(),
        )
        return metrics

    if not total:
        return _result()

    sem = asyncio.Semaphore(max_concurrent)
    # La `Connection` SA sync n'est pas thread-safe ; les writes concurrents d'un paquet passent par `to_thread` sous ce lock (le commit, lui, se fait à la frontière de paquet, hors concurrence).
    db_lock = asyncio.Lock()

    async with httpx.AsyncClient() as client:

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
                    await asyncio.to_thread(publication_repo.update_oa_status, pub_id, new_status)
                else:
                    await asyncio.to_thread(publication_repo.mark_unpaywall_checked, pub_id)

        # Traitement par paquets : chaque paquet part en concurrence (débit borné par `sem`) puis est committé.
        for start in range(0, total, BATCH_SIZE):
            chunk = pubs[start : start + BATCH_SIZE]
            await asyncio.gather(*(process_one(*pub) for pub in chunk))
            await asyncio.to_thread(conn.commit)
            done = min(start + BATCH_SIZE, total)
            logger.info(
                f"  {done}/{total} — {progress['updated']} mis à jour, "
                f"{progress['skipped']} inchangés, {progress['not_found']} non trouvés"
            )

    logger.info(
        f"Terminé : {progress['updated']} mis à jour, {progress['skipped']} inchangés, "
        f"{progress['not_found']} non trouvés sur Unpaywall"
    )

    return _result()
