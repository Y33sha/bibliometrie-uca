"""
Import croisé : récupère sur OpenAlex les DOI présents dans HAL/WoS
mais absents de la base OpenAlex.

Usage:
    python cross_import_openalex.py              # import complet
    python cross_import_openalex.py --dry-run    # compter seulement
    python cross_import_openalex.py --limit 100  # limiter le nombre de DOI
    python cross_import_openalex.py --normalize  # normaliser après import

Étapes :
  1. Identifie les DOI HAL/WoS absents du staging OpenAlex
  2. Interroge l'API OpenAlex pour chaque DOI
  3. Insère les works trouvés dans staging_openalex (processed=FALSE)
  4. (optionnel) Lance la normalisation sur les nouveaux works
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
from psycopg2.extras import Json, execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import OPENALEX
from db.connection import get_connection

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "cross_import_openalex.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org/works"

SELECT_FIELDS = ",".join([
    "id", "doi", "title", "display_name", "publication_year",
    "publication_date", "type", "language", "primary_location",
    "locations", "authorships", "open_access", "cited_by_count",
    "biblio", "is_retracted",
])


def get_missing_dois(conn) -> list[str]:
    """
    Retourne les DOI présents dans HAL ou WoS mais absents
    du staging OpenAlex (et des openalex_documents).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT doi FROM (
                SELECT doi FROM hal_documents WHERE doi IS NOT NULL
                UNION
                SELECT doi FROM wos_documents WHERE doi IS NOT NULL
            ) src
            WHERE doi NOT IN (
                SELECT doi FROM staging_openalex WHERE doi IS NOT NULL
            )
            AND doi NOT IN (
                SELECT doi FROM openalex_documents WHERE doi IS NOT NULL
            )
            ORDER BY doi
        """)
        return [row[0] for row in cur.fetchall()]


def compute_hash(raw_data: dict) -> str:
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def extract_openalex_id(work: dict) -> str:
    return work["id"].replace("https://openalex.org/", "")


def extract_doi(work: dict) -> str | None:
    doi = work.get("doi")
    if doi:
        return doi.replace("https://doi.org/", "").strip()
    return None


def fetch_by_doi(doi: str) -> dict | None:
    """Interroge l'API OpenAlex pour un DOI donné. Retourne le work ou None."""
    params = {
        "filter": f"doi:{doi}",
        "select": SELECT_FIELDS,
        "mailto": OPENALEX["email"],
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            return results[0]
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        logger.warning(f"Erreur API pour {doi}: {e}")
    except Exception as e:
        logger.warning(f"Erreur pour {doi}: {e}")
    return None


def insert_work(conn, work: dict):
    """Insère un work dans staging_openalex."""
    oa_id = extract_openalex_id(work)
    doi = extract_doi(work)
    raw_hash = compute_hash(work)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO staging_openalex (openalex_id, doi, raw_data, raw_hash, processed)
            VALUES (%s, %s, %s::jsonb, %s, FALSE)
            ON CONFLICT (openalex_id) DO NOTHING
        """, (oa_id, doi, Json(work), raw_hash))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Import croisé DOI → OpenAlex")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans importer")
    parser.add_argument("--limit", type=int, help="Nombre max de DOI à traiter")
    parser.add_argument("--normalize", action="store_true",
                        help="Lancer la normalisation après import")
    args = parser.parse_args()

    conn = get_connection()
    try:
        dois = get_missing_dois(conn)
        logger.info(f"{len(dois)} DOI à chercher sur OpenAlex")

        if args.dry_run:
            logger.info("Mode dry-run — aucun import effectué.")
            return

        if args.limit:
            dois = dois[:args.limit]
            logger.info(f"Limité à {len(dois)} DOI")

        found = 0
        not_found = 0
        errors = 0

        for i, doi in enumerate(dois):
            work = fetch_by_doi(doi)
            if work:
                insert_work(conn, work)
                found += 1
            else:
                not_found += 1

            if (i + 1) % 100 == 0:
                logger.info(
                    f"  {i+1}/{len(dois)} traités — "
                    f"{found} trouvés, {not_found} absents"
                )

            time.sleep(OPENALEX["request_delay"])

        logger.info(
            f"=== Terminé : {found} works importés, "
            f"{not_found} absents d'OpenAlex, {errors} erreurs ==="
        )

        if args.normalize and found > 0:
            logger.info("Lancement de la normalisation...")
            conn.close()
            os.execvp(
                sys.executable,
                [sys.executable,
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "..", "processing", "normalize_openalex.py")]
            )

    except KeyboardInterrupt:
        logger.warning("Interruption — les données déjà insérées sont conservées.")
    finally:
        if not conn.closed:
            conn.close()


if __name__ == "__main__":
    main()
