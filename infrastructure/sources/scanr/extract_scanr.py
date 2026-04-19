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
from typing import Any

from psycopg2.extras import Json

from infrastructure.api_limits import SCANR_DELAY, SCANR_PER_PAGE
from infrastructure.api_retry import http_request_with_retry
from infrastructure.app_config import (
    get_api_base_urls,
    get_scanr_affiliation_ids,
    get_scanr_credentials,
    get_years,
)
from infrastructure.sources.base import ExtractionStats, SourceExtractor, run_extractor
from infrastructure.sources.common import clean_doi, compute_hash, setup_logger

logger = setup_logger("extract_scanr", os.path.join(os.path.dirname(__file__), "logs"))


def build_query(year: int, affiliation_ids: list[str], search_after: list | None = None) -> dict:
    """Construit la requête Elasticsearch pour ScanR."""
    query = {
        "size": SCANR_PER_PAGE,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [{"term": {"year": year}}],
                "should": [{"term": {"affiliations.id.keyword": aid}} for aid in affiliation_ids],
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
    """Exécute une requête Elasticsearch (avec retry/backoff)."""
    return http_request_with_retry(
        "POST",
        url,
        json_body=query,
        auth=auth,
        timeout=30,
        label="ScanR search",
    )


def extract_year(
    conn: Any,
    url: str,
    auth: tuple,
    year: int,
    affiliation_ids: list[str],
    existing_ids: set,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait toutes les publications d'une année. Retourne (total, insérés, mis à jour)."""
    search_after = None
    inserted = 0
    updated = 0
    seen = 0

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
                cur.execute(
                    """
                    UPDATE staging
                    SET raw_data = %s, doi = %s, raw_hash = %s, last_seen_at = now()
                    WHERE source = 'scanr' AND source_id = %s AND (raw_hash IS DISTINCT FROM %s)
                    """,
                    (Json(doc), doi, raw_hash, scanr_id, raw_hash),
                )
                if cur.rowcount:
                    updated += 1
            else:
                cur.execute(
                    """
                    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
                    VALUES ('scanr', %s, %s, %s, %s)
                    ON CONFLICT (source, source_id) DO NOTHING
                    """,
                    (scanr_id, doi, Json(doc), raw_hash),
                )
                if cur.rowcount:
                    inserted += 1
                    existing_ids.add(scanr_id)

        search_after = hits[-1]["sort"]

        if seen % 2000 == 0:
            conn.commit()
            logger.info(f"    {seen}/{total} traités ({inserted} nouveaux, {updated} mis à jour)")

        time.sleep(SCANR_DELAY)

    conn.commit()
    return total, inserted, updated


class ScanrExtractor(SourceExtractor):
    SOURCE = "scanr"
    DESCRIPTION = "Extraction ScanR → staging"

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année unique")

    def load_config(self, cur: Any) -> dict[str, Any]:
        username, password = get_scanr_credentials(cur)
        return {
            "years": get_years(cur),
            "affiliation_ids": get_scanr_affiliation_ids(cur),
            "auth": (username, password),
            "url": get_api_base_urls(cur).get(
                "scanr",
                "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
            ),
        }

    def setup_logging(self, args: argparse.Namespace, config: dict[str, Any]) -> None:
        years = [args.year] if args.year else config["years"]
        self.logger.info(
            f"=== Extraction ScanR : années {years}, "
            f"{len(config['affiliation_ids'])} structures ==="
        )

    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> ExtractionStats:
        years = [args.year] if args.year else config["years"]
        stats = ExtractionStats()
        for year in years:
            total, inserted, updated = extract_year(
                self.conn,
                config["url"],
                config["auth"],
                year,
                config["affiliation_ids"],
                existing_ids,
                dry_run=args.dry_run,
            )
            stats.add(new=inserted, updated=updated, total=total)
            self.logger.info(f"  {year} terminé : {inserted} nouveaux, {updated} mis à jour")
        return stats

    def log_summary(self, stats: ExtractionStats, args: argparse.Namespace) -> None:
        self.logger.info("\n=== Terminé ===")
        self.logger.info(f"Total API : {stats.total}")
        self.logger.info(f"Nouveaux : {stats.new}")
        self.logger.info(f"Mis à jour : {stats.updated}")


def main() -> None:
    run_extractor(ScanrExtractor, logger)


if __name__ == "__main__":
    main()
