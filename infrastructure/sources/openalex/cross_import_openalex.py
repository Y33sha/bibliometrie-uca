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
  3. Insère les works trouvés dans staging (processed=FALSE)
  4. (optionnel) Lance la normalisation sur les nouveaux works
"""

import argparse
import os
import sys
import time
from typing import Any

import requests
from psycopg2.extras import Json

from infrastructure.api_limits import OPENALEX_DELAY
from infrastructure.app_config import get_openalex_api_key, get_openalex_email
from infrastructure.db.connection import get_connection
from infrastructure.sources.common import compute_hash, get_cross_import_dois, setup_logger
from infrastructure.sources.openalex import (
    BASE_URL,
    SELECT_FIELDS,
    auth_params,
    extract_doi,
    extract_openalex_id,
    init_auth,
)

# ----- Logging -----
logger = setup_logger("cross_import_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def fetch_by_doi(doi: str) -> dict | None:
    """Interroge l'API OpenAlex pour un DOI donné. Retourne le work ou None."""
    params = {
        "filter": f"doi:{doi}",
        "select": SELECT_FIELDS,
        **auth_params(),
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


def insert_work(conn: Any, work: dict) -> Any:
    """Insère un work dans staging."""
    oa_id = extract_openalex_id(work)
    doi = extract_doi(work)
    raw_hash = compute_hash(work)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
            VALUES ('openalex', %s, %s, %s::jsonb, %s, FALSE)
            ON CONFLICT (source, source_id) DO NOTHING
        """,
            (oa_id, doi, Json(work), raw_hash),
        )
    conn.commit()


def main() -> Any:
    parser = argparse.ArgumentParser(description="Import croisé DOI → OpenAlex")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans importer")
    parser.add_argument("--limit", type=int, help="Nombre max de DOI à traiter")
    parser.add_argument(
        "--normalize", action="store_true", help="Lancer la normalisation après import"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Considérer tout le staging (pas seulement les non-normalisés)",
    )
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    init_auth(api_key=get_openalex_api_key(cur), email=get_openalex_email(cur))
    cur.close()
    try:
        dois = get_cross_import_dois(conn, "openalex", all_staged=args.all)
        logger.info(f"{len(dois)} DOI à chercher sur OpenAlex")

        if args.dry_run:
            logger.info("Mode dry-run — aucun import effectué.")
            return

        if args.limit:
            dois = dois[: args.limit]
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
                logger.info(f"  {i + 1}/{len(dois)} traités — {found} trouvés, {not_found} absents")

            time.sleep(OPENALEX_DELAY)

        logger.info(
            f"=== Terminé : {found} works importés, "
            f"{not_found} absents d'OpenAlex, {errors} erreurs ==="
        )

        if args.normalize and found > 0:
            logger.info("Lancement de la normalisation...")
            conn.close()
            os.execvp(
                sys.executable,
                [
                    sys.executable,
                    os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..",
                        "processing",
                        "normalize_openalex.py",
                    ),
                ],
            )

    except KeyboardInterrupt:
        logger.warning("Interruption — les données déjà insérées sont conservées.")
    finally:
        if not conn.closed:
            conn.close()


if __name__ == "__main__":
    main()
