"""
Phase pipeline `oa_status` — enrichit `publications.oa_status` via Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour
le statut OA. Écrase les valeurs existantes, SAUF : ne remplace jamais
'diamond' par 'gold' (Unpaywall ne connaît pas le diamond OA).

Cette phase ne contient qu'un seul sub-step (Unpaywall). Elle s'appelait
`enrich` avant 2026-05-26, rebaptisée après l'extraction de la phase
`publishers_journals` qui a absorbé `enrich_journal_apc`. Le nom `enrich`
était devenu un misnomer (countries/subjects/publishers_journals
enrichissent aussi).

L'orchestrateur dépend du port `EnrichQueries` et reçoit en injection
un `OaStatusFetcher` (le fetcher concret vit dans
`infrastructure/sources/unpaywall.py` pour respecter l'étanchéité DDD).
Le point d'entrée CLI (argparse + connexion + `asyncio.run`) est dans
`interfaces/cli/pipeline/enrich_oa_status.py`.

Implémentation async : `httpx.AsyncClient` partagé +
`asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import Connection

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
STALENESS_DAYS = 30
"""Au-delà, un statut OA changeable (hors STABLE_OA_STATUSES) est re-vérifié."""


async def run_enrich_oa_status(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    fetcher: OaStatusFetcher,
    limit: int = 0,
    dry_run: bool = False,
    max_concurrent: int = MAX_CONCURRENT,
) -> None:
    pubs = queries.fetch_publications_with_doi(
        conn, limit=limit or MAX_PER_RUN, staleness_days=STALENESS_DAYS
    )
    total = len(pubs)
    logger.info(
        f"{total} publications à (re)vérifier sur Unpaywall "
        f"(cap {limit or MAX_PER_RUN}, staleness {STALENESS_DAYS}j)"
    )

    if not total:
        return

    sem = asyncio.Semaphore(max_concurrent)
    # La `Connection` SA sync n'est pas thread-safe ; tous les writes
    # (update, commit) passent par `to_thread` sous ce lock.
    db_lock = asyncio.Lock()
    progress = {"processed": 0, "updated": 0, "skipped": 0, "not_found": 0}

    async with httpx.AsyncClient() as client:

        async def process_one(pub_id: int, doi: str, current_status: str | None) -> None:
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
            else:
                new_status = status
                progress["updated"] += 1
                if dry_run:
                    logger.info(f"  [DRY] {doi} : {current_status} → {status}")

            if not dry_run:
                async with db_lock:
                    if new_status is not None:
                        await asyncio.to_thread(pub_repo.update_oa_status, pub_id, new_status)
                    else:
                        await asyncio.to_thread(pub_repo.mark_unpaywall_checked, pub_id)

            progress["processed"] += 1
            if progress["processed"] % BATCH_SIZE == 0:
                if not dry_run:
                    async with db_lock:
                        await asyncio.to_thread(conn.commit)
                logger.info(
                    f"  {progress['processed']}/{total} — "
                    f"{progress['updated']} mis à jour, "
                    f"{progress['skipped']} inchangés, "
                    f"{progress['not_found']} non trouvés"
                )

        await asyncio.gather(*(process_one(pid, doi, cur) for pid, doi, cur in pubs))

    if not dry_run:
        conn.commit()

    logger.info(
        f"Terminé : {progress['updated']} mis à jour, {progress['skipped']} inchangés, "
        f"{progress['not_found']} non trouvés sur Unpaywall"
    )
