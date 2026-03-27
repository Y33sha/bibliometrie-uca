"""
Enrichit staging_hal.raw_data avec les champs composés alignés.

Champs ajoutés :
  - authFullNameIdHal_fs  : nom_FacetSep_idhal (aligné)
  - authFullNameId_fs     : nom_FacetSep_personId (aligné)
  - authIdHasStructure_fs : affiliation auteur→structure par document

Usage:
    python patch_staging_idhal.py           # enrichir tout le staging
    python patch_staging_idhal.py --limit 50  # tester sur 50 docs
    python patch_staging_idhal.py --dry-run   # compter seulement
"""

import argparse
import logging
import os
import sys
import time
import json

import requests
import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://api.archives-ouvertes.fr/search/"
NEW_FIELDS = [
    "authFullNameIdHal_fs",
    "authFullNameId_fs",
    "authIdHasStructure_fs",
    "structIdName_fs",           # id_FacetSep_nom — fiable
]
BATCH_SIZE = 100  # HAL accepte des requêtes par lot de halId


def fetch_batch(hal_ids: list[str]) -> dict:
    """Interroge HAL pour un batch de halId, retourne {halid: {field: values}}."""
    ids_query = " OR ".join(f'"{hid}"' for hid in hal_ids)
    params = {
        "q": f"halId_s:({ids_query})",
        "fl": "halId_s," + ",".join(NEW_FIELDS),
        "rows": len(hal_ids),
        "wt": "json",
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for doc in data.get("response", {}).get("docs", []):
        halid = doc.get("halId_s")
        if halid:
            extras = {}
            for f in NEW_FIELDS:
                if f in doc:
                    extras[f] = doc[f]
            if extras:
                result[halid] = extras
    return result


def main():
    parser = argparse.ArgumentParser(description="Patch staging_hal avec champs auteur composés")
    parser.add_argument("--limit", type=int, help="Nombre max de docs à traiter")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Compter les docs sans les champs
    cur.execute("""
        SELECT COUNT(*) FROM staging_hal
        WHERE NOT (raw_data ? 'structIdName_fs')
    """)
    to_patch = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM staging_hal")
    total = cur.fetchone()[0]

    logger.info(f"Staging HAL : {total} docs, {to_patch} sans structIdName_fs")

    if args.dry_run:
        cur.close()
        conn.close()
        return

    # Récupérer les halId à patcher
    limit_clause = f"LIMIT {args.limit}" if args.limit else ""
    cur.execute(f"""
        SELECT halid FROM staging_hal
        WHERE NOT (raw_data ? 'structIdName_fs')
        ORDER BY id
        {limit_clause}
    """)
    hal_ids = [r[0] if isinstance(r, tuple) else r['halid'] for r in cur.fetchall()]
    logger.info(f"  {len(hal_ids)} docs à enrichir")

    patched = 0
    no_data = 0

    for i in range(0, len(hal_ids), BATCH_SIZE):
        batch = hal_ids[i:i + BATCH_SIZE]
        try:
            results = fetch_batch(batch)
        except Exception as e:
            logger.error(f"  Erreur batch {i}: {e}")
            time.sleep(2)
            continue

        for halid in batch:
            extras = results.get(halid)
            if extras:
                cur.execute("""
                    UPDATE staging_hal
                    SET raw_data = raw_data || %s::jsonb
                    WHERE halid = %s
                """, (Json(extras), halid))
                patched += 1
            else:
                no_data += 1

        conn.commit()

        done = min(i + BATCH_SIZE, len(hal_ids))
        if done % 1000 < BATCH_SIZE or done >= len(hal_ids):
            logger.info(f"  {done}/{len(hal_ids)} traités "
                        f"({patched} enrichis, {no_data} sans données)")

        time.sleep(0.2)

    logger.info(f"\n=== Terminé : {patched} docs enrichis, {no_data} sans données ===")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
