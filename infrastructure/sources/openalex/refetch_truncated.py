"""
Re-fetch des publications OpenAlex tronquées à 100 auteurs.

L'API OpenAlex bulk retourne max 100 authorships par work. Ce script
détecte les works avec exactement 100 auteurs dans le staging et les
re-fetche individuellement via l'API (qui retourne alors tous les auteurs).

Implémentation async : `httpx.AsyncClient` partagé + `asyncio.Semaphore(3)`
pour respecter le plafond OpenAlex (~10 req/s, cf. fetch_missing_doi).

Usage:
    python refetch_truncated.py              # re-fetch complet
    python refetch_truncated.py --dry-run    # compter seulement
    python refetch_truncated.py --limit 50   # limiter le nombre
"""

import argparse
import asyncio
import os

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.pipeline_metrics import PhaseMetrics
from infrastructure.db.engine import get_sync_engine
from infrastructure.sources.common import setup_logger
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_openalex_email,
)
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth

MAX_CONCURRENT = 3
COMMIT_EVERY = 50

# Le refetch ne recalcule **pas** `raw_hash` : la ligne garde le hash du
# payload bulk initial. Cette dissymétrie volontaire est le mécanisme de
# préservation : tant que le bulk renvoie le même payload tronqué, son
# hash matchera celui en base et l'UPSERT bulk ne touchera pas `raw_data`
# (qui contient pourtant les auteurs complets). Un changement bulk
# (raw_hash diffèrent) écrasera raw_data avec la version tronquée, et le
# prochain passage du refetch dans le même run pipeline (count repassé à
# 100) ré-amorcera le cycle.
_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, processed = FALSE, last_seen_at = now()
    WHERE id = :id
    """
).bindparams(bindparam("raw_data", type_=JSONB))

logger = setup_logger("refetch_truncated", os.path.join(os.path.dirname(__file__), "logs"))


async def fetch_work(client: httpx.AsyncClient, openalex_id: str, *, base_url: str) -> dict | None:
    """Fetch un work individuel par son ID OpenAlex (retourne tous les auteurs).

    Retourne le dict ou None si l'API renvoie 404 (work introuvable) ou
    si la requête a échoué après tous les retries.
    """
    url = f"{base_url}/{openalex_id}"
    params = {"select": SELECT_FIELDS, **auth_params()}
    try:
        return await http_request_with_retry_async(
            client, "GET", url, params=params, timeout=30, label=f"OA {openalex_id}"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            logger.warning(f"Erreur API pour {openalex_id}: HTTP {e.response.status_code}")
        return None
    except httpx.RequestError as e:
        logger.warning(f"Erreur réseau pour {openalex_id}: {e}")
        return None


async def refetch(
    conn: Connection,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    max_concurrent: int = MAX_CONCURRENT,
) -> PhaseMetrics:
    """Re-fetch les works OpenAlex avec exactement 100 authorships.

    Phase importable depuis `run_pipeline.py` ; ne ferme pas la connexion
    (responsabilité du caller). `updated` compte les works ré-écrits ;
    `already_complete` (extras) ceux qui avaient pile 100 auteurs ;
    `errors` les fetchs échoués.
    """
    init_auth(api_key=get_openalex_api_key(conn), email=get_openalex_email(conn))
    base_url = get_api_base_urls(conn)["openalex"]

    truncated = conn.execute(
        text(
            """
            SELECT id, source_id
            FROM staging
            WHERE source = 'openalex'
              AND processed = FALSE
              AND jsonb_array_length(raw_data->'authorships') = 100
            ORDER BY id
            """
        )
    ).all()
    if limit:
        truncated = truncated[:limit]
    logger.info(f"{len(truncated)} works avec 100 auteurs détectés (potentiellement tronqués)")

    metrics = PhaseMetrics(total=len(truncated))
    if not truncated or dry_run:
        return metrics

    sem = asyncio.Semaphore(max_concurrent)
    # La `Connection` SA sync n'est pas thread-safe ; tous les writes
    # (UPDATE, commit) passent par `to_thread` sous ce lock.
    db_lock = asyncio.Lock()
    progress = {"processed": 0}

    def _apply_update(staging_id: int, work: dict) -> None:
        conn.execute(
            _UPDATE_SQL,
            {
                "raw_data": work,
                "id": staging_id,
            },
        )

    async with httpx.AsyncClient() as client:

        async def process_one(staging_id: int, openalex_id: str) -> None:
            async with sem:
                work = await fetch_work(client, openalex_id, base_url=base_url)

            if not work:
                metrics.add(errors=1)
            elif len(work.get("authorships", [])) <= 100:
                metrics.add(already_complete=1)
            else:
                async with db_lock:
                    await asyncio.to_thread(_apply_update, staging_id, work)
                metrics.add(updated=1)

            progress["processed"] += 1
            if progress["processed"] % COMMIT_EVERY == 0:
                async with db_lock:
                    await asyncio.to_thread(conn.commit)
                logger.info(
                    f"  {progress['processed']}/{len(truncated)}... "
                    f"({metrics.updated} mis à jour, "
                    f"{metrics.extras.get('already_complete', 0)} déjà complets)"
                )

        await asyncio.gather(*(process_one(row.id, row.source_id) for row in truncated))

    conn.commit()
    logger.info(
        f"Terminé : {metrics.updated} works mis à jour avec authorships complètes, "
        f"{metrics.extras.get('already_complete', 0)} déjà complets, "
        f"{metrics.errors} erreurs"
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-fetch publications OA tronquées (>= 100 auteurs)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        asyncio.run(refetch(conn, dry_run=args.dry_run, limit=args.limit))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
