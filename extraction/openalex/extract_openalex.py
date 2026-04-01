"""
Extraction des publications UCA depuis l'API OpenAlex.

Usage:
    python extract_openalex.py              # extraction complète 2022-2025
    python extract_openalex.py --year 2024  # une seule année
    python extract_openalex.py --dry-run    # compte les résultats sans insérer

L'API OpenAlex est interrogée via le filtre institution (ROR) + année.
Les résultats bruts sont stockés dans staging_openalex (JSONB).
Les works déjà présents (même openalex_id) sont ignorés.
"""

import argparse
import json
import logging
import sys
import os
import time

import hashlib
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
            os.path.join(os.path.dirname(__file__), "logs", "extract_openalex.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

# ----- Constantes API -----
BASE_URL = "https://api.openalex.org/works"


def build_params(year: int, cursor: str = "*") -> dict:
    """Construit les paramètres de requête pour l'API OpenAlex."""
    # Support liste d'IDs institution (OR via pipe)
    ids = OPENALEX.get("institution_ids") or [OPENALEX.get("institution_id")]
    lineage_filter = "|".join(ids)
    params = {
        "filter": (
            f"authorships.institutions.lineage:{lineage_filter},"
            f"publication_year:{year}"
        ),
        # Champs à récupérer — on prend large pour le staging,
        # la sélection fine se fera à l'étape de normalisation
        "select": ",".join([
            "id",
            "doi",
            "title",
            "display_name",
            "publication_year",
            "publication_date",
            "type",
            "language",
            "primary_location",
            "locations",
            "authorships",
            "open_access",
            "cited_by_count",
            "biblio",
            "is_retracted",
        ]),
        "per_page": OPENALEX["per_page"],
        "cursor": cursor,
        "mailto": OPENALEX["email"],
    }
    return params


def fetch_page(year: int, cursor: str = "*") -> dict:
    """Récupère une page de résultats depuis l'API."""
    params = build_params(year, cursor)
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_doi(work: dict) -> str | None:
    """Extrait le DOI nettoyé (sans préfixe https://doi.org/)."""
    doi = work.get("doi")
    if doi:
        return doi.replace("https://doi.org/", "").strip()
    return None


def extract_openalex_id(work: dict) -> str:
    """Extrait l'ID OpenAlex court (ex: W2741809807)."""
    return work["id"].replace("https://openalex.org/", "")


def get_existing_ids(conn) -> set:
    """Récupère les openalex_id déjà en base pour éviter les doublons."""
    with conn.cursor() as cur:
        cur.execute("SELECT openalex_id FROM staging_openalex")
        return {row[0] for row in cur.fetchall()}


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def insert_batch(conn, batch: list[tuple]):
    """Insère un batch de works dans staging_openalex.
    Si le work existe et que le hash a changé, met à jour raw_data et remet processed = FALSE.
    """
    query = """
        INSERT INTO staging_openalex (openalex_id, doi, raw_data, raw_hash)
        VALUES %s
        ON CONFLICT (openalex_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging_openalex.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                    THEN EXCLUDED.raw_data
                ELSE staging_openalex.raw_data
            END,
            raw_hash = COALESCE(EXCLUDED.raw_hash, staging_openalex.raw_hash),
            processed = CASE
                WHEN staging_openalex.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                    THEN FALSE
                ELSE staging_openalex.processed
            END,
            last_seen_at = now()
    """
    with conn.cursor() as cur:
        execute_values(
            cur, query, batch,
            template="(%s, %s, %s::jsonb, %s)"
        )
    conn.commit()


def extract_year(year: int, conn, existing_ids: set, dry_run: bool = False) -> int:
    """
    Extrait toutes les publications d'une année.
    Retourne le nombre de works insérés.
    """
    cursor = "*"
    total_fetched = 0
    total_inserted = 0
    page_num = 0

    # Premier appel pour avoir le count total
    first_page = fetch_page(year, cursor)
    total_count = first_page["meta"]["count"]
    logger.info(f"Année {year} : {total_count} works trouvés sur OpenAlex")

    if dry_run:
        return 0

    while True:
        page_num += 1

        if page_num == 1:
            data = first_page
        else:
            data = fetch_page(year, cursor)

        results = data.get("results", [])
        if not results:
            break

        # Préparer le batch
        batch = []
        new_count = 0
        for work in results:
            oa_id = extract_openalex_id(work)
            doi = extract_doi(work)
            raw_hash = compute_hash(work)
            batch.append((oa_id, doi, Json(work), raw_hash))
            if oa_id not in existing_ids:
                existing_ids.add(oa_id)
                new_count += 1

        # Insérer / mettre à jour
        if batch:
            insert_batch(conn, batch)
            total_inserted += new_count

        total_fetched += len(results)
        logger.info(
            f"  Page {page_num} : {len(results)} works récupérés, "
            f"{new_count} nouveaux "
            f"({total_fetched}/{total_count} traités, {total_inserted} nouveaux au total)"
        )

        # Pagination cursor
        next_cursor = data["meta"].get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

        time.sleep(OPENALEX["request_delay"])

    logger.info(
        f"Année {year} terminée : {total_inserted} works insérés "
        f"sur {total_fetched} récupérés ({total_count} au total sur OpenAlex)"
    )
    return total_inserted


def main():
    parser = argparse.ArgumentParser(description="Extraction OpenAlex → staging")
    parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
    args = parser.parse_args()

    years = [args.year] if args.year else OPENALEX["years"]

    logger.info(f"=== Extraction OpenAlex démarrée ===")
    ids = OPENALEX.get("institution_ids") or [OPENALEX.get("institution_id")]
    logger.info(f"Institutions OpenAlex : {', '.join(ids)} (lineage OR)")
    logger.info(f"Années : {years}")

    conn = get_connection()
    try:
        existing_ids = get_existing_ids(conn)
        logger.info(f"{len(existing_ids)} works déjà en staging")

        grand_total = 0
        for year in years:
            inserted = extract_year(year, conn, existing_ids, dry_run=args.dry_run)
            grand_total += inserted

        logger.info(f"=== Terminé : {grand_total} works insérés au total ===")

    except requests.exceptions.HTTPError as e:
        logger.error(f"Erreur API : {e}")
        logger.error(f"Réponse : {e.response.text[:500] if e.response else 'N/A'}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Interruption utilisateur — les données déjà insérées sont conservées.")
        sys.exit(0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
