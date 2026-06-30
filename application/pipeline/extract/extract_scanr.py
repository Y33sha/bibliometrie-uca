"""Orchestrateur d'extraction ScanR.

Pilote l'extraction par année via la pagination `search_after`
(Elasticsearch). Le détail HTTP/SQL est délégué à `ScanrExtractAdapter`.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import Connection

from application.pipeline.extract.base import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.scanr import ScanrExtractAdapter, ScanrExtractConfig


def extract_year(
    adapter: ScanrExtractAdapter,
    conn: Connection,
    year: int,
    affiliation_ids: list[str],
    logger: ExtractLogger,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int, int]:
    """Extrait toutes les publications d'une année.

    Retourne (total, nouveaux, mis à jour, inchangés)."""
    search_after: list | None = None
    inserted = 0
    updated = 0
    unchanged = 0
    seen = 0
    total = 0

    while True:
        first_page = search_after is None
        query = adapter.build_query(year, affiliation_ids, search_after, track_total=first_page)
        data = adapter.fetch_page(query)

        if first_page:
            total = data["hits"]["total"]["value"]
            logger.info(f"{total} publications")
            if dry_run:
                return total, 0, 0, 0

        hits = data["hits"]["hits"]
        if not hits:
            break

        for hit in hits:
            doc = hit["_source"]
            scanr_id = adapter.extract_id(doc)
            if not scanr_id:
                continue

            seen += 1
            was_new, was_updated, was_unchanged = adapter.upsert_doc(conn, doc)
            if was_new:
                inserted += 1
            elif was_updated:
                updated += 1
            elif was_unchanged:
                unchanged += 1

        search_after = hits[-1]["sort"]

        if seen % 500 == 0:
            conn.commit()
            logger.info(
                f"{seen}/{total} traités "
                f"({inserted} nouveaux, {updated} mis à jour, {unchanged} inchangés)"
            )

    conn.commit()
    return total, inserted, updated, unchanged


class ScanrExtractor(SourceExtractor[ScanrExtractConfig]):
    """Extraction ScanR — orchestrateur applicatif."""

    SOURCE = "scanr"
    DESCRIPTION = "Extraction ScanR → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        adapter: ScanrExtractAdapter,
    ) -> None:
        super().__init__(conn, logger)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année unique")
        parser.add_argument(
            "--start-year",
            type=int,
            help="Année de début du range (défaut: config pipeline_start_year_full)",
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
        self.logger.info(f"Structures : {len(config.affiliation_ids)}")

    def extract_all(self, args: argparse.Namespace, config: ScanrExtractConfig) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, start_year=args.start_year)
        years = [args.year] if args.year else config_years
        self.logger.info(f"Années : {years}")
        stats = PhaseMetrics()
        for year in years:
            if self._breaker_tripped():
                self.logger.warning(
                    "ScanR à bout (429/5xx répétés) — années restantes sautées"
                    " (retry au prochain run)"
                )
                break
            slog = scoped_logger(self.logger, self.SOURCE, str(year))
            total, inserted, updated, unchanged = extract_year(
                self._adapter,
                self.conn,
                year,
                config.affiliation_ids,
                slog,
                dry_run=args.dry_run,
            )
            stats.add(new=inserted, updated=updated, unchanged=unchanged, total=total)
            slog.info(f"terminé : {inserted} nouveaux, {updated} mis à jour, {unchanged} inchangés")
        return stats

    # log_summary : on hérite du défaut de SourceExtractor (`=== Terminé : as_summary ===`)
    # — format harmonisé entre tous les extracteurs.


__all__ = [
    "ScanrExtractor",
    "extract_year",
]
