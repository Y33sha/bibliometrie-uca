"""
Phase pipeline `oa_status` — enrichit `publications.oa_status` via Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour
le statut OA. Écrase les valeurs existantes, SAUF : (1) ne remplace jamais
'diamond' par 'gold' (Unpaywall ne connaît pas le diamond OA) ; (2) ne
rétrograde jamais 'embargoed' vers 'closed'/'unknown' (l'embargo est connu
côté HAL, Unpaywall voit juste le fichier non encore accessible) — un statut
plus ouvert (green+) écrase bien.

Cette phase ne contient qu'un seul sub-step (Unpaywall). Elle s'appelait
`enrich` avant 2026-05-26, rebaptisée après l'extraction de la phase
`publishers_journals` qui a absorbé `enrich_journal_apc`. Le nom `enrich`
était devenu un misnomer (countries/subjects/publishers_journals
enrichissent aussi).

L'orchestrateur dépend du port `EnrichQueries` et reçoit en injection
un `OaStatusFetcher` (le fetcher concret vit dans
`infrastructure/sources/unpaywall.py` pour respecter l'étanchéité DDD).
Appelé par `run_pipeline` (phase `oa_status`), qui gère la connexion et
`asyncio.run`.

Implémentation async : `httpx.AsyncClient` partagé +
`asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.publication_repository import PublicationRepository

type OaStatusFetcher = Callable[[httpx.AsyncClient, str], Awaitable[str | None]]
"""Signature : ``(client, doi) → statut OA mappé (str) | None``."""

BATCH_SIZE = 50
MAX_CONCURRENT = 5

# Constantes opérationnelles (pas métier — la règle métier des statuts stables est
# dans domain/publications/metadata.STABLE_OA_STATUSES).
MAX_PER_RUN = 10_000
"""Cap de DOI vérifiés par run : lisse la charge (le backlog des jamais-vérifiés
s'écoule sur plusieurs runs au lieu d'un pic de ~100k)."""
STALENESS_DAYS = 15
"""Au-delà, un statut OA changeable (hors STABLE_OA_STATUSES) est re-vérifié.

Borne le décalage entre une bascule OA côté Unpaywall (qui peut rétrodater une
`oa_date` sans notifier) et sa prise en compte : au pire, un statut périmé
survit une fenêtre avant re-vérification."""


async def run_enrich_oa_status(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    fetcher: OaStatusFetcher,
    limit: int = 0,
    max_concurrent: int = MAX_CONCURRENT,
) -> PhaseMetrics:
    logger.info("▶ enrich_oa_status")
    t0 = time.perf_counter()
    metrics = PhaseMetrics()
    pubs = queries.fetch_publications_with_doi(
        conn, limit=limit or MAX_PER_RUN, staleness_days=STALENESS_DAYS
    )
    total = len(pubs)
    stale_total = queries.count_stale_publications(conn, staleness_days=STALENESS_DAYS)
    before_dist = queries.count_publications_by_oa_status(conn)
    logger.info(
        f"{total} publications à (re)vérifier sur Unpaywall "
        f"(cap {limit or MAX_PER_RUN}, staleness {STALENESS_DAYS}j) — {stale_total} stale au total"
    )

    progress = {"processed": 0, "updated": 0, "skipped": 0, "not_found": 0}

    def _result() -> PhaseMetrics:
        # Indicateurs : synthèse du run (backlog, vérifiées, ventilation) puis répartition
        # des publications par statut OA avec le delta du run (avant → après).
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
    # La `Connection` SA sync n'est pas thread-safe ; tous les writes
    # (update, commit) passent par `to_thread` sous ce lock.
    db_lock = asyncio.Lock()

    async with httpx.AsyncClient() as client:

        async def process_one(
            pub_id: int, doi: str, current_status: str | None, has_open_deposit: bool
        ) -> None:
            async with sem:
                status = await fetcher(client, doi)

            # `new_status` non None = on écrit un nouveau statut ; sinon on pose juste
            # `unpaywall_checked_at` (vérifié, rien à changer) pour ne pas re-tirer ce
            # DOI au run suivant.
            new_status: str | None = None
            if status is None:
                progress["not_found"] += 1
            elif (current_status == "diamond" and status == "gold") or status == current_status:
                # diamond préservé (Unpaywall ne le connaît pas) ou statut inchangé.
                progress["skipped"] += 1
            elif current_status == "embargoed" and status in ("closed", "unknown"):
                # embargo connu (HAL) : pas de rétrogradation vers closed/unknown.
                progress["skipped"] += 1
            elif has_open_deposit and status in ("closed", "unknown"):
                # Une archive ouverte détient le fichier (HAL green) : Unpaywall ne le voit pas sous
                # le DOI, il ne peut pas refermer le dépôt. On marque vérifié sans rétrograder.
                progress["skipped"] += 1
            else:
                new_status = status
                progress["updated"] += 1

            async with db_lock:
                if new_status is not None:
                    await asyncio.to_thread(pub_repo.update_oa_status, pub_id, new_status)
                else:
                    await asyncio.to_thread(pub_repo.mark_unpaywall_checked, pub_id)

            progress["processed"] += 1
            if progress["processed"] % BATCH_SIZE == 0:
                async with db_lock:
                    await asyncio.to_thread(conn.commit)
                logger.info(
                    f"  {progress['processed']}/{total} — "
                    f"{progress['updated']} mis à jour, "
                    f"{progress['skipped']} inchangés, "
                    f"{progress['not_found']} non trouvés"
                )

        await asyncio.gather(
            *(
                process_one(pid, doi, current, has_deposit)
                for pid, doi, current, has_deposit in pubs
            )
        )

    conn.commit()

    logger.info(
        f"Terminé : {progress['updated']} mis à jour, {progress['skipped']} inchangés, "
        f"{progress['not_found']} non trouvés sur Unpaywall"
    )

    return _result()
