"""
Import croisé : récupère sur HAL les DOI présents dans OpenAlex/WoS
mais absents de la base HAL.

Usage:
    python cross_import_hal.py              # import complet
    python cross_import_hal.py --dry-run    # compter seulement
    python cross_import_hal.py --limit 100  # limiter le nombre de DOI
    python cross_import_hal.py --normalize  # normaliser après import

Étapes :
  1. Identifie les DOI OpenAlex/WoS absents du staging HAL
  2. Interroge l'API HAL pour chaque DOI
  3. Insère les documents trouvés dans staging (collection=NULL, processed=FALSE)
  4. (optionnel) Lance la normalisation sur les nouveaux documents
"""

import argparse
import os
import sys
import time

import requests
from psycopg2.extras import Json

from db.connection import get_connection
from extraction.common import compute_hash, get_cross_import_dois, setup_logger
from utils.hal import HAL_FIELDS_STR

# ----- Logging -----
logger = setup_logger("cross_import_hal", os.path.join(os.path.dirname(__file__), "logs"))

HAL_API = "https://api.archives-ouvertes.fr/search"



def fetch_by_doi(doi: str) -> dict | None:
    """Interroge l'API HAL pour un DOI donné. Retourne le document ou None."""
    params = {
        "q": f"doiId_s:\"{doi}\"",
        "fl": HAL_FIELDS_STR,
        "wt": "json",
        "rows": 1,
    }
    try:
        resp = requests.get(HAL_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("response", {}).get("docs", [])
        if docs:
            return docs[0]
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Erreur API pour {doi}: {e}")
    except Exception as e:
        logger.warning(f"Erreur pour {doi}: {e}")
    return None


def insert_staging(conn, doc: dict):
    """Insere un document dans staging avec ses collections HAL."""
    hal_id = doc.get("halId_s")
    if isinstance(hal_id, list):
        hal_id = hal_id[0] if hal_id else None
    if not hal_id:
        return

    doi = doc.get("doiId_s")
    if isinstance(doi, list):
        doi = doi[0] if doi else None

    # Extraire les collections du document
    coll_codes = doc.get("collCode_s") or []
    hal_collections = coll_codes if isinstance(coll_codes, list) and coll_codes else None

    raw_hash = compute_hash(doc)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed, raw_hash)
            VALUES ('hal', %s, %s, %s::jsonb, %s, FALSE, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                raw_data = CASE
                    WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN EXCLUDED.raw_data
                    ELSE staging.raw_data
                END,
                raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
                hal_collections = CASE
                    WHEN staging.hal_collections IS NULL THEN EXCLUDED.hal_collections
                    WHEN EXCLUDED.hal_collections IS NULL THEN staging.hal_collections
                    ELSE (SELECT array_agg(DISTINCT c) FROM unnest(staging.hal_collections || EXCLUDED.hal_collections) AS c)
                END,
                processed = CASE
                    WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN FALSE
                    ELSE staging.processed
                END
        """, (hal_id, doi, Json(doc), hal_collections, raw_hash))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Import croisé DOI → HAL")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans importer")
    parser.add_argument("--limit", type=int, help="Nombre max de DOI à traiter")
    parser.add_argument("--normalize", action="store_true",
                        help="Lancer la normalisation après import")
    parser.add_argument("--all", action="store_true",
                        help="Considérer tout le staging (pas seulement les non-normalisés)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        dois = get_cross_import_dois(conn, "hal", all_staged=args.all)
        logger.info(f"{len(dois)} DOI à chercher sur HAL")

        if args.dry_run:
            logger.info("Mode dry-run — aucun import effectué.")
            return

        if args.limit:
            dois = dois[:args.limit]
            logger.info(f"Limité à {len(dois)} DOI")

        found = 0
        not_found = 0

        for i, doi in enumerate(dois):
            doc = fetch_by_doi(doi)
            if doc:
                insert_staging(conn, doc)
                found += 1
            else:
                not_found += 1

            if (i + 1) % 100 == 0:
                logger.info(
                    f"  {i+1}/{len(dois)} traités — "
                    f"{found} trouvés, {not_found} absents"
                )

            time.sleep(0.5)

        logger.info(
            f"=== Terminé : {found} documents importés, "
            f"{not_found} absents de HAL ==="
        )
        logger.info("Relancer normalize_hal.py pour les integrer")

        if args.normalize and found > 0:
            logger.info("Lancement de la normalisation...")
            conn.close()
            os.execvp(
                sys.executable,
                [sys.executable,
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "..", "processing", "normalize_hal.py")]
            )

    except KeyboardInterrupt:
        logger.warning("Interruption — les données déjà insérées sont conservées.")
    finally:
        if not conn.closed:
            conn.close()


if __name__ == "__main__":
    main()
