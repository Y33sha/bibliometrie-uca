"""
Import croisé : récupère sur ScanR les DOI présents dans HAL/OA/WoS
mais absents du staging ScanR.

Usage:
    python cross_import_scanr.py              # import complet
    python cross_import_scanr.py --dry-run    # compter seulement
    python cross_import_scanr.py --limit 100  # limiter le nombre de DOI

Étapes :
  1. Identifie les DOI HAL/OA/WoS absents du staging ScanR
  2. Interroge l'API ScanR par batch de DOI
  3. Insère les publications trouvées dans staging_scanr (processed=FALSE)
"""

import argparse
import os
import sys
import time

import requests
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import SCANR
from db.connection import get_connection
from extraction.common import compute_hash, clean_doi, setup_logger
from utils.app_config import get_scanr_credentials

logger = setup_logger("cross_import_scanr", os.path.join(os.path.dirname(__file__), "logs"))

BATCH_SIZE = 50  # nombre de DOI par requête ES (terms query)


def get_missing_dois(conn) -> list[str]:
    """DOI présents dans d'autres sources mais absents du staging ScanR."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT doi FROM (
                SELECT doi FROM staging_hal WHERE doi IS NOT NULL
                UNION
                SELECT doi FROM staging_openalex WHERE doi IS NOT NULL
                UNION
                SELECT doi FROM staging_wos WHERE doi IS NOT NULL
            ) src
            WHERE lower(doi) NOT IN (
                SELECT lower(doi) FROM staging_scanr WHERE doi IS NOT NULL
            )
            ORDER BY doi
        """)
        return [row[0] for row in cur.fetchall()]


def fetch_by_dois(url: str, auth: tuple, dois: list[str]) -> list[dict]:
    """Recherche un batch de DOI dans ScanR. Retourne les _source trouvés."""
    query = {
        "size": len(dois),
        "query": {
            "terms": {"externalIds.id.keyword": dois}
        }
    }
    resp = requests.post(url, json=query, auth=auth, timeout=30)
    resp.raise_for_status()
    return [hit["_source"] for hit in resp.json()["hits"]["hits"]]


def main():
    parser = argparse.ArgumentParser(description="Cross-import ScanR")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Nombre max de DOI")
    args = parser.parse_args()

    conn = get_connection()
    username, password = get_scanr_credentials(conn.cursor())
    url = SCANR.get("base_url",
                     "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search")
    auth = (username, password)

    missing = get_missing_dois(conn)
    if args.limit:
        missing = missing[:args.limit]

    logger.info(f"=== Cross-import ScanR : {len(missing)} DOI manquants ===")

    if args.dry_run:
        logger.info("Dry-run — rien inséré.")
        conn.close()
        return

    cur = conn.cursor()
    inserted = 0
    not_found = 0

    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i:i + BATCH_SIZE]
        try:
            docs = fetch_by_dois(url, auth, batch)
        except Exception as e:
            logger.error(f"Erreur batch {i}–{i+len(batch)}: {e}")
            time.sleep(2)
            continue

        found_dois = set()
        for doc in docs:
            scanr_id = doc.get("id", "")
            doi = None
            for ext in doc.get("externalIds") or []:
                if ext.get("type") == "doi":
                    doi = clean_doi(ext.get("id"))
                    break
            if not scanr_id:
                continue

            found_dois.add(doi.lower() if doi else "")
            raw_hash = compute_hash(doc)

            cur.execute("""
                INSERT INTO staging_scanr (scanr_id, doi, raw_data, raw_hash)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (scanr_id) DO NOTHING
            """, (scanr_id, doi, Json(doc), raw_hash))
            if cur.rowcount:
                inserted += 1

        not_found += len(batch) - len(docs)

        if (i + BATCH_SIZE) % 1000 == 0 or i + BATCH_SIZE >= len(missing):
            conn.commit()
            logger.info(f"  {min(i + BATCH_SIZE, len(missing))}/{len(missing)} "
                        f"({inserted} insérés, {not_found} non trouvés)")

        time.sleep(SCANR.get("request_delay", 0.3))

    conn.commit()
    logger.info(f"\n=== Terminé : {inserted} insérés, {not_found} non trouvés ===")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
