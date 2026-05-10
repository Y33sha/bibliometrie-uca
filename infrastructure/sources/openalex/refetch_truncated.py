"""
Re-fetch des publications OpenAlex tronquées à 100 auteurs.

L'API OpenAlex bulk retourne max 100 authorships par work. Ce script
détecte les works avec exactement 100 auteurs dans le staging et les
re-fetche individuellement via l'API (qui retourne alors tous les auteurs).

Usage:
    python refetch_truncated.py              # re-fetch complet
    python refetch_truncated.py --dry-run    # compter seulement
    python refetch_truncated.py --limit 50   # limiter le nombre
"""

import argparse
import os
import time

import requests
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.api_limits import OPENALEX_DELAY
from infrastructure.app_config import get_api_base_urls, get_openalex_api_key, get_openalex_email
from infrastructure.db.engine import get_sync_engine
from infrastructure.sources.common import compute_hash, setup_logger
from infrastructure.sources.openalex import (
    SELECT_FIELDS,
    auth_params,
    compute_meta_hash,
    init_auth,
)

_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, raw_hash = :raw_hash, meta_hash = :meta_hash,
        processed = FALSE, last_seen_at = now()
    WHERE id = :id
    """
).bindparams(bindparam("raw_data", type_=JSONB))

logger = setup_logger("refetch_truncated", os.path.join(os.path.dirname(__file__), "logs"))


def fetch_work(openalex_id: str, *, base_url: str) -> dict | None:
    """Fetch un work individuel par son ID OpenAlex (retourne tous les auteurs)."""
    url = f"{base_url}/{openalex_id}"
    params = {"select": SELECT_FIELDS, **auth_params()}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        logger.warning(f"Erreur API pour {openalex_id}: {e}")
    except Exception as e:
        logger.warning(f"Erreur pour {openalex_id}: {e}")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-fetch publications OA tronquées (>= 100 auteurs)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    init_auth(api_key=get_openalex_api_key(conn), email=get_openalex_email(conn))
    base_url = get_api_base_urls(conn)["openalex"]

    # Détecter les works avec exactement 100 authorships dans le staging
    truncated = conn.execute(
        text(
            """
            SELECT id, source_id
            FROM staging
            WHERE source = 'openalex'
              AND jsonb_array_length(raw_data->'authorships') = 100
            ORDER BY id
            """
        )
    ).all()

    if args.limit:
        truncated = truncated[: args.limit]

    logger.info(f"{len(truncated)} works avec 100 auteurs détectés (potentiellement tronqués)")

    if not truncated or args.dry_run:
        conn.close()
        return

    updated = 0
    already_complete = 0
    errors = 0

    for i, row in enumerate(truncated):
        work = fetch_work(row.source_id, base_url=base_url)
        time.sleep(OPENALEX_DELAY)

        if not work:
            errors += 1
            continue

        if len(work.get("authorships", [])) <= 100:
            # Pas réellement tronqué (la publication a exactement 100 auteurs)
            already_complete += 1
            continue

        conn.execute(
            _UPDATE_SQL,
            {
                "raw_data": work,
                "raw_hash": compute_hash(work),
                "meta_hash": compute_meta_hash(work),
                "id": row.id,
            },
        )
        updated += 1

        if (i + 1) % 50 == 0:
            conn.commit()
            logger.info(
                f"  {i + 1}/{len(truncated)}... ({updated} mis à jour, {already_complete} déjà complets)"
            )

    conn.commit()
    conn.close()

    logger.info(
        f"Terminé : {updated} works mis à jour avec authorships complètes, "
        f"{already_complete} déjà complets, {errors} erreurs"
    )


if __name__ == "__main__":
    main()
