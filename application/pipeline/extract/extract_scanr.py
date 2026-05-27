"""Orchestrateur d'extraction ScanR.

Pilote l'extraction par année via la pagination `search_after`
(Elasticsearch). Le détail HTTP/SQL est délégué à `ScanrExtractAdapter`.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import Connection

from application.pipeline.extract.base import ExtractionConfigError, SourceExtractor
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.scanr import ScanrExtractAdapter, ScanrExtractConfig
from application.ports.pipeline.staging import StagingQueries


def extract_year(
    adapter: ScanrExtractAdapter,
    conn: Connection,
    year: int,
    affiliation_ids: list[str],
    existing_ids: set[str],
    logger: logging.Logger,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait toutes les publications d'une année. Retourne (total, insérés, mis à jour)."""
    search_after: list | None = None
    inserted = 0
    updated = 0
    seen = 0

    query = adapter.build_query(year, affiliation_ids)
    data = adapter.fetch_page(query)
    total = data["hits"]["total"]["value"]
    logger.info(f"  {year} : {total} publications")

    if dry_run:
        return total, 0, 0

    while True:
        query = adapter.build_query(year, affiliation_ids, search_after)
        data = adapter.fetch_page(query)
        hits = data["hits"]["hits"]
        if not hits:
            break

        for hit in hits:
            doc = hit["_source"]
            scanr_id = adapter.extract_id(doc)
            if not scanr_id:
                continue

            seen += 1
            is_new = scanr_id not in existing_ids
            was_inserted, was_updated = adapter.upsert_doc(conn, doc, is_new=is_new)
            if was_inserted:
                inserted += 1
                existing_ids.add(scanr_id)
            elif was_updated:
                updated += 1

        search_after = hits[-1]["sort"]

        if seen % 500 == 0:
            conn.commit()
            logger.info(f"    {seen}/{total} traités ({inserted} nouveaux, {updated} mis à jour)")

    conn.commit()
    return total, inserted, updated


class ScanrExtractor(SourceExtractor[ScanrExtractConfig]):
    """Extraction ScanR — orchestrateur applicatif."""

    SOURCE = "scanr"
    DESCRIPTION = "Extraction ScanR → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging: StagingQueries,
        adapter: ScanrExtractAdapter,
    ) -> None:
        super().__init__(conn, logger, staging)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année unique")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )

    def load_config(self, conn: Connection) -> ScanrExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.affiliation_ids:
            raise ExtractionConfigError(
                "aucun affiliation_id ScanR configuré "
                "(structures.api_ids->'scanr' vide pour le périmètre d'extraction)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: ScanrExtractConfig) -> None:
        self.logger.info(f"=== Extraction ScanR : {len(config.affiliation_ids)} structures ===")

    def extract_all(
        self,
        args: argparse.Namespace,
        config: ScanrExtractConfig,
        existing_ids: set[str],
    ) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years
        self.logger.info(f"Années : {years}")
        stats = PhaseMetrics()
        for year in years:
            total, inserted, updated = extract_year(
                self._adapter,
                self.conn,
                year,
                config.affiliation_ids,
                existing_ids,
                self.logger,
                dry_run=args.dry_run,
            )
            stats.add(new=inserted, updated=updated, total=total)
            self.logger.info(f"  {year} terminé : {inserted} nouveaux, {updated} mis à jour")
        return stats

    # log_summary : on hérite du défaut de SourceExtractor (`=== Terminé : as_summary ===`)
    # — format harmonisé entre tous les extracteurs.


__all__ = [
    "ScanrExtractor",
    "extract_year",
]
