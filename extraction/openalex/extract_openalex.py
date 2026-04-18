"""
Extraction des publications UCA depuis l'API OpenAlex.

Usage:
    python extract_openalex.py              # extraction complète 2022-2025
    python extract_openalex.py --year 2024  # une seule année
    python extract_openalex.py --dry-run    # compte les résultats sans insérer

L'API OpenAlex est interrogée via le filtre institution (ROR) + année.
Les résultats bruts sont stockés dans staging (JSONB).
Les works déjà présents (même openalex_id) sont ignorés.
"""

import argparse
import os
import sys
import time

import requests
from psycopg2.extras import Json, execute_values

from db.connection import get_connection
from extraction.common import compute_hash, get_existing_ids, setup_logger
from extraction.openalex import (
    SELECT_FIELDS,
    auth_params,
    compute_meta_hash,
    extract_doi,
    extract_openalex_id,
    init_auth,
)
from infrastructure.api_limits import OPENALEX_DELAY, OPENALEX_PER_PAGE
from infrastructure.api_retry import http_request_with_retry
from infrastructure.app_config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_openalex_email,
    get_openalex_institution_ids,
    get_years,
)

# ----- Logging -----
logger = setup_logger("extract_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def build_params(
    year: int = None, cursor: str = "*", institution_ids: list[str] | None = None, since: str = None
) -> dict:
    """Construit les paramètres de requête pour l'API OpenAlex.

    Si since est fourni (YYYY-MM-DD), filtre sur from_updated_date
    au lieu de filtrer par année.
    """
    lineage_filter = "|".join(institution_ids or [])
    if since:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},from_updated_date:{since}"
    else:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},publication_year:{year}"
    return {
        "filter": filter_str,
        "select": SELECT_FIELDS,
        "per_page": OPENALEX_PER_PAGE,
        "cursor": cursor,
        **auth_params(),
    }


def fetch_page(
    base_url: str,
    year: int = None,
    cursor: str = "*",
    institution_ids: list[str] = None,
    since: str = None,
) -> dict:
    """Récupère une page de résultats depuis l'API OpenAlex (avec retry/backoff)."""
    params = build_params(year, cursor, institution_ids=institution_ids, since=since)
    label = f"OpenAlex {since or year}"
    return http_request_with_retry("GET", base_url, params=params, timeout=30, label=label)


def insert_batch(conn, batch: list[tuple]) -> int:
    """Insère un batch de works dans staging.

    Logique de mise à jour :
    - Compare meta_hash (métadonnées hors authorships) pour détecter les vrais changements
    - Si meta_hash identique → rien à faire
    - Si meta_hash différent → met à jour raw_data en préservant les authorships de la
      version en base si elle en a plus (cas des works >100 auteurs déjà re-fetchés)

    Retourne le nombre de documents dont les métadonnées ont changé.
    """
    query = """
        INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, meta_hash)
        VALUES %s
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.raw_data
                WHEN jsonb_array_length(staging.raw_data->'authorships')
                     > jsonb_array_length(EXCLUDED.raw_data->'authorships')
                    THEN jsonb_set(staging.raw_data,
                         '{title}', EXCLUDED.raw_data->'title')
                      || jsonb_build_object(
                         'open_access', EXCLUDED.raw_data->'open_access',
                         'primary_location', EXCLUDED.raw_data->'primary_location',
                         'locations', EXCLUDED.raw_data->'locations',
                         'cited_by_count', EXCLUDED.raw_data->'cited_by_count',
                         'type', EXCLUDED.raw_data->'type',
                         'language', EXCLUDED.raw_data->'language',
                         'biblio', EXCLUDED.raw_data->'biblio',
                         'is_retracted', EXCLUDED.raw_data->'is_retracted')
                ELSE EXCLUDED.raw_data
            END,
            raw_hash = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.raw_hash
                ELSE EXCLUDED.raw_hash
            END,
            meta_hash = COALESCE(EXCLUDED.meta_hash, staging.meta_hash),
            processed = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.processed
                ELSE FALSE
            END,
            last_seen_at = now()
    """
    with conn.cursor() as cur:
        # Compter les documents existants avec un meta_hash différent
        source_ids = [b[1] for b in batch]
        cur.execute(
            """
            SELECT source_id, meta_hash FROM staging
            WHERE source = 'openalex' AND source_id = ANY(%s)
        """,
            (source_ids,),
        )
        old_hashes = {r[0]: r[1] for r in cur.fetchall()}

        execute_values(cur, query, batch, template="(%s, %s, %s, %s::jsonb, %s, %s)")
    conn.commit()

    # Compter les mises à jour réelles (meta_hash différent, document existant)
    updated = 0
    for _, source_id, _, _, _, meta_hash in batch:
        old = old_hashes.get(source_id)
        if old is not None and old != meta_hash:
            updated += 1
    return updated


def extract_year(
    year: int = None,
    conn=None,
    existing_ids: set = None,
    base_url: str = "",
    institution_ids: list[str] = None,
    since: str = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait des publications OpenAlex par année ou par date de modification.
    Retourne (nouveaux, mis_a_jour).
    """
    cursor = "*"
    total_fetched = 0
    total_new = 0
    total_updated = 0
    page_num = 0

    # Premier appel pour avoir le count total
    first_page = fetch_page(base_url, year, cursor, institution_ids=institution_ids, since=since)
    total_count = first_page["meta"]["count"]
    label = f"depuis {since}" if since else f"année {year}"
    logger.info(f"{label} : {total_count} works trouvés sur OpenAlex")

    if dry_run:
        return 0, 0

    while True:
        page_num += 1

        if page_num == 1:
            data = first_page
        else:
            data = fetch_page(base_url, year, cursor, institution_ids=institution_ids, since=since)

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
            meta_hash = compute_meta_hash(work)
            batch.append(("openalex", oa_id, doi, Json(work), raw_hash, meta_hash))
            if oa_id not in existing_ids:
                existing_ids.add(oa_id)
                new_count += 1

        # Insérer / mettre à jour
        updated_count = 0
        if batch:
            updated_count = insert_batch(conn, batch)
            total_new += new_count
            total_updated += updated_count

        total_fetched += len(results)
        parts = []
        if new_count:
            parts.append(f"{new_count} nouveaux")
        if updated_count:
            parts.append(f"{updated_count} mis à jour")
        if not parts:
            parts.append("aucun changement")
        logger.info(
            f"  Page {page_num} : {len(results)} works — {', '.join(parts)} "
            f"({total_fetched}/{total_count})"
        )

        # Pagination cursor
        next_cursor = data["meta"].get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

        time.sleep(OPENALEX_DELAY)

    logger.info(
        f"Année {year} terminée : {total_new} nouveaux, {total_updated} mis à jour "
        f"(sur {total_fetched} récupérés, {total_count} sur OpenAlex)"
    )
    return total_new, total_updated


def main():
    parser = argparse.ArgumentParser(description="Extraction OpenAlex → staging")
    parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
    parser.add_argument(
        "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
    )
    parser.add_argument(
        "--since",
        help="Date ISO (YYYY-MM-DD) : ne récupérer que les documents modifiés depuis cette date",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    institution_ids = get_openalex_institution_ids(cur)
    init_auth(api_key=get_openalex_api_key(cur), email=get_openalex_email(cur))
    base_url = get_api_base_urls(cur).get("openalex", "https://api.openalex.org/works")
    config_years = get_years(cur, mode=args.mode)
    cur.close()

    since = args.since
    years = [args.year] if args.year else config_years

    logger.info("=== Extraction OpenAlex démarrée ===")
    logger.info(f"Institutions OpenAlex : {', '.join(institution_ids)} (lineage OR)")
    if since:
        logger.info(f"Mode incrémental : documents modifiés depuis {since}")
    else:
        logger.info(f"Années : {years}")
    try:
        existing_ids = get_existing_ids(conn, "openalex")
        logger.info(f"{len(existing_ids)} works déjà en staging")

        grand_new = 0
        grand_updated = 0
        if since:
            year_new, year_updated = extract_year(
                conn=conn,
                existing_ids=existing_ids,
                base_url=base_url,
                institution_ids=institution_ids,
                since=since,
                dry_run=args.dry_run,
            )
            grand_new += year_new
            grand_updated += year_updated
        else:
            for year in years:
                year_new, year_updated = extract_year(
                    year,
                    conn,
                    existing_ids,
                    base_url=base_url,
                    institution_ids=institution_ids,
                    dry_run=args.dry_run,
                )
            grand_new += year_new
            grand_updated += year_updated

        logger.info(f"=== Terminé : {grand_new} nouveaux, {grand_updated} mis à jour ===")

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
