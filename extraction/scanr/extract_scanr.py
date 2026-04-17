"""
Extraction des publications depuis l'API ScanR (Elasticsearch MESR).

Usage:
    python extract_scanr.py                # extraction complète
    python extract_scanr.py --year 2024    # une seule année
    python extract_scanr.py --dry-run      # compter sans insérer

L'API est un Elasticsearch interrogé via search_after pour la pagination.
Les résultats bruts sont stockés dans staging (JSONB).
"""

import argparse
import os
import time

import requests
from psycopg2.extras import Json

from db.connection import get_connection
from extraction.common import compute_hash, clean_doi, get_existing_ids, setup_logger
from utils.app_config import get_years, get_scanr_affiliation_ids, get_scanr_credentials, get_api_base_urls

PER_PAGE = 500
REQUEST_DELAY = 0.3

logger = setup_logger("extract_scanr", os.path.join(os.path.dirname(__file__), "logs"))


def build_query(year: int, affiliation_ids: list[str],
                search_after: list | None = None) -> dict:
    """Construit la requête Elasticsearch pour ScanR."""
    query = {
        "size": PER_PAGE,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [{"term": {"year": year}}],
                "should": [
                    {"term": {"affiliations.id.keyword": aid}}
                    for aid in affiliation_ids
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"id.keyword": "asc"}],
    }
    if search_after:
        query["search_after"] = search_after
    return query


def extract_scanr_id(doc: dict) -> str:
    """Extrait l'identifiant ScanR (champ id du document)."""
    return doc.get("id", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI depuis les externalIds."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None


def fetch_page(url: str, auth: tuple, query: dict) -> dict:
    """Exécute une requête Elasticsearch."""
    resp = requests.post(url, json=query, auth=auth, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_year(conn, url: str, auth: tuple, year: int,
                 affiliation_ids: list[str], existing_ids: set,
                 dry_run: bool = False) -> tuple[int, int, int]:
    """Extrait toutes les publications d'une année. Retourne (total, insérés, mis à jour)."""
    search_after = None
    inserted = 0
    updated = 0
    seen = 0

    # Premier appel pour connaître le total
    query = build_query(year, affiliation_ids)
    data = fetch_page(url, auth, query)
    total = data["hits"]["total"]["value"]
    logger.info(f"  {year} : {total} publications")

    if dry_run:
        return total, 0, 0

    cur = conn.cursor()

    while True:
        query = build_query(year, affiliation_ids, search_after)
        data = fetch_page(url, auth, query)
        hits = data["hits"]["hits"]

        if not hits:
            break

        for hit in hits:
            doc = hit["_source"]
            scanr_id = extract_scanr_id(doc)
            if not scanr_id:
                continue

            doi = extract_doi(doc)
            raw_hash = compute_hash(doc)
            seen += 1

            if scanr_id in existing_ids:
                # Mettre à jour si le hash a changé
                cur.execute("""
                    UPDATE staging
                    SET raw_data = %s, doi = %s, raw_hash = %s, last_seen_at = now()
                    WHERE source = 'scanr' AND source_id = %s AND (raw_hash IS DISTINCT FROM %s)
                """, (Json(doc), doi, raw_hash, scanr_id, raw_hash))
                if cur.rowcount:
                    updated += 1
            else:
                cur.execute("""
                    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
                    VALUES ('scanr', %s, %s, %s, %s)
                    ON CONFLICT (source, source_id) DO NOTHING
                """, (scanr_id, doi, Json(doc), raw_hash))
                if cur.rowcount:
                    inserted += 1
                    existing_ids.add(scanr_id)

        # Pagination search_after
        search_after = hits[-1]["sort"]

        if seen % 2000 == 0:
            conn.commit()
            logger.info(f"    {seen}/{total} traités ({inserted} nouveaux, {updated} mis à jour)")

        time.sleep(REQUEST_DELAY)

    conn.commit()
    return total, inserted, updated


def main():
    parser = argparse.ArgumentParser(description="Extraction ScanR → staging")
    parser.add_argument("--year", type=int, help="Année unique")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    years = [args.year] if args.year else get_years(cur)
    affiliation_ids = get_scanr_affiliation_ids(cur)
    username, password = get_scanr_credentials(cur)
    url = get_api_base_urls(cur).get("scanr",
          "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search")
    auth = (username, password)

    logger.info(f"=== Extraction ScanR : années {years}, {len(affiliation_ids)} structures ===")

    if not args.dry_run:
        existing_ids = get_existing_ids(conn, "scanr")
        logger.info(f"  {len(existing_ids)} documents déjà en staging")
    else:
        existing_ids = set()

    grand_total = 0
    grand_inserted = 0
    grand_updated = 0

    for year in years:
        total, inserted, updated = extract_year(
            conn, url, auth, year, affiliation_ids, existing_ids,
            dry_run=args.dry_run
        )
        grand_total += total
        grand_inserted += inserted
        grand_updated += updated
        logger.info(f"  {year} terminé : {inserted} nouveaux, {updated} mis à jour")

    logger.info(f"\n=== Terminé ===")
    logger.info(f"Total API : {grand_total}")
    logger.info(f"Nouveaux : {grand_inserted}")
    logger.info(f"Mis à jour : {grand_updated}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
