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

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.pipeline_metrics import PhaseMetrics
from infrastructure.sources.api_limits import SCANR_DELAY
from infrastructure.sources.base import (
    ExtractionConfigError,
    SourceExtractor,
    run_extractor,
)
from infrastructure.sources.common import compute_hash, setup_logger
from infrastructure.sources.config import (
    get_api_base_urls,
    get_extraction_api_ids,
    get_scanr_credentials,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry
from infrastructure.sources.scanr.parsing import build_query, extract_doi, extract_scanr_id

logger = setup_logger("extract_scanr", os.path.join(os.path.dirname(__file__), "logs"))

_UPDATE_SCANR_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, doi = :doi, raw_hash = :raw_hash, last_seen_at = now()
    WHERE source = 'scanr' AND source_id = :source_id AND (raw_hash IS DISTINCT FROM :raw_hash)
    """
).bindparams(bindparam("raw_data", type_=JSONB))

_INSERT_SCANR_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('scanr', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO NOTHING
    """
).bindparams(bindparam("raw_data", type_=JSONB))


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
    conn: Connection,
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
                result = conn.execute(
                    _UPDATE_SCANR_SQL,
                    {
                        "raw_data": doc,
                        "doi": doi,
                        "raw_hash": raw_hash,
                        "source_id": scanr_id,
                    },
                )
                if result.rowcount:
                    updated += 1
            else:
                result = conn.execute(
                    _INSERT_SCANR_SQL,
                    {
                        "source_id": scanr_id,
                        "doi": doi,
                        "raw_data": doc,
                        "raw_hash": raw_hash,
                    },
                )
                if result.rowcount:
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
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )

    def load_config(self, conn: Connection) -> dict[str, Any]:
        affiliation_ids = get_extraction_api_ids(conn, "scanr")
        if not affiliation_ids:
            raise ExtractionConfigError(
                "aucun affiliation_id ScanR configuré "
                "(structures.api_ids->'scanr' vide pour le périmètre d'extraction)"
            )
        username, password = get_scanr_credentials(conn)
        return {
            "affiliation_ids": affiliation_ids,
            "auth": (username, password),
            "url": get_api_base_urls(conn).get(
                "scanr",
                "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
            ),
        }

    def setup_logging(self, args: argparse.Namespace, config: dict[str, Any]) -> None:
        self.logger.info(f"=== Extraction ScanR : {len(config['affiliation_ids'])} structures ===")

    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> PhaseMetrics:
        config_years = get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years
        self.logger.info(f"Années : {years}")
        stats = PhaseMetrics()
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

    def log_summary(self, stats: PhaseMetrics, args: argparse.Namespace) -> None:
        self.logger.info("\n=== Terminé ===")
        self.logger.info(f"Total API : {stats.total}")
        self.logger.info(f"Nouveaux : {stats.new}")
        self.logger.info(f"Mis à jour : {stats.updated}")


def main() -> None:
    run_extractor(ScanrExtractor, logger)


if __name__ == "__main__":
    main()
