"""
Enrichissement du statut Open Access via l'API Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour
le statut OA. Écrase les valeurs existantes, SAUF : ne remplace jamais
'diamond' par 'gold' (Unpaywall ne connaît pas le diamond OA).

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
from typing import TypeAlias

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.publication_repository import PublicationRepository

OaStatusFetcher: TypeAlias = Callable[[httpx.AsyncClient, str], Awaitable[str | None]]
"""Signature : ``(client, doi) → statut OA mappé (str) | None``."""

BATCH_SIZE = 50
MAX_CONCURRENT = 5


async def run_enrich(
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
    pubs = queries.fetch_publications_with_doi(conn, limit=limit or None)
    total = len(pubs)
    logger.info(f"{total} publications avec DOI à vérifier sur Unpaywall")

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

            if status is None:
                progress["not_found"] += 1
            elif current_status == "diamond" and status == "gold":
                # Préservation : Unpaywall ne connaît pas diamond, ne pas écraser.
                progress["skipped"] += 1
            elif status == current_status:
                progress["skipped"] += 1
            elif dry_run:
                logger.info(f"  [DRY] {doi} : {current_status} → {status}")
                progress["updated"] += 1
            else:
                async with db_lock:
                    await asyncio.to_thread(pub_repo.update_oa_status, pub_id, status)
                progress["updated"] += 1

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
