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
  3. Insère les documents trouvés dans staging_hal (collection=NULL, processed=FALSE)
  4. (optionnel) Lance la normalisation sur les nouveaux documents
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time

import requests
import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import HAL
from db.connection import get_connection

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "cross_import_hal.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

HAL_API = "https://api.archives-ouvertes.fr/search"
HAL_FIELDS = (
    "halId_s,docid,doiId_s,title_s,subTitle_s,"
    "authFullName_s,authIdHal_s,authOrcid_s,authIdHal_i,"
    "authFullNameIdHal_fs,authFullNameId_fs,"
    "authFullNameFormIDPersonIDIDHal_fs,authIdHasStructure_fs,"
    "producedDateY_i,publicationDate_s,docType_s,language_s,"
    "journalTitle_s,journalIssn_s,journalEissn_s,journalPublisher_s,"
    "bookTitle_s,publisher_s,conferenceTitle_s,"
    "openAccess_bool,linkExtUrl_s,uri_s,label_s,"
    "collCode_s,structId_i,structName_s,structType_s,structAcronym_s"
)


def get_missing_dois(conn) -> list[str]:
    """
    Retourne les DOI présents dans OpenAlex ou WoS mais absents
    du staging HAL (et des hal_documents).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT doi FROM (
                SELECT doi FROM openalex_documents WHERE doi IS NOT NULL
                UNION
                SELECT doi FROM wos_documents WHERE doi IS NOT NULL
            ) src
            WHERE doi NOT IN (
                SELECT doi FROM staging_hal WHERE doi IS NOT NULL
            )
            AND doi NOT IN (
                SELECT doi FROM hal_documents WHERE doi IS NOT NULL
            )
            ORDER BY doi
        """)
        return [row[0] for row in cur.fetchall()]


def compute_hash(raw_data: dict) -> str:
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def fetch_by_doi(doi: str) -> dict | None:
    """Interroge l'API HAL pour un DOI donné. Retourne le document ou None."""
    params = {
        "q": f"doiId_s:\"{doi}\"",
        "fl": HAL_FIELDS,
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


def insert_staging_hal(conn, doc: dict):
    """Insère un document dans staging_hal avec collection=NULL."""
    hal_id = doc.get("halId_s")
    if isinstance(hal_id, list):
        hal_id = hal_id[0] if hal_id else None
    if not hal_id:
        return

    doi = doc.get("doiId_s")
    if isinstance(doi, list):
        doi = doi[0] if doi else None

    raw_hash = compute_hash(doc)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO staging_hal (halid, doi, raw_data, collection, processed, raw_hash)
            VALUES (%s, %s, %s::jsonb, NULL, FALSE, %s)
            ON CONFLICT (halid) DO UPDATE SET
                raw_data = CASE
                    WHEN staging_hal.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN EXCLUDED.raw_data
                    ELSE staging_hal.raw_data
                END,
                raw_hash = COALESCE(EXCLUDED.raw_hash, staging_hal.raw_hash),
                processed = CASE
                    WHEN staging_hal.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN FALSE
                    ELSE staging_hal.processed
                END
        """, (hal_id, doi, Json(doc), raw_hash))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Import croisé DOI → HAL")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans importer")
    parser.add_argument("--limit", type=int, help="Nombre max de DOI à traiter")
    parser.add_argument("--normalize", action="store_true",
                        help="Lancer la normalisation après import")
    args = parser.parse_args()

    conn = get_connection()
    try:
        dois = get_missing_dois(conn)
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
                insert_staging_hal(conn, doc)
                found += 1
            else:
                not_found += 1

            if (i + 1) % 100 == 0:
                logger.info(
                    f"  {i+1}/{len(dois)} traités — "
                    f"{found} trouvés, {not_found} absents"
                )

            time.sleep(HAL["request_delay"])

        logger.info(
            f"=== Terminé : {found} documents importés, "
            f"{not_found} absents de HAL ==="
        )
        logger.info("Les entrées insérées ont collection = NULL (hors périmètre)")
        logger.info("Relancer normalize_hal.py pour les intégrer")

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
