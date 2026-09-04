"""Orchestrateur d'extraction ScanR.

Pilote l'extraction par année via la pagination `search_after` (Elasticsearch). Le détail HTTP/SQL est délégué à `ScanrExtractAdapter`.
"""

from __future__ import annotations

import argparse

from sqlalchemy import Connection

from application.pipeline.extract.base import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.scanr import ScanrExtractAdapter, ScanrExtractConfig
from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path


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
    search_after: list[JsonValue] | None = None
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
            total = as_int(at_path(data, "hits", "total").get("value")) or 0
            logger.info("%s publications", total)
            if dry_run:
                return total, 0, 0, 0

        hits = [as_mapping(h) for h in as_sequence(at_path(data, "hits").get("hits"))]
        if not hits:
            break

        for hit in hits:
            doc = as_mapping(hit.get("_source"))
            scanr_id = adapter.extract_id(doc)
            if not scanr_id:
                continue

            seen += 1
            outcome = adapter.upsert_doc(conn, doc)
            if outcome is UpsertOutcome.NEW:
                inserted += 1
            elif outcome is UpsertOutcome.UPDATED:
                updated += 1
            else:
                unchanged += 1

        search_after = list(as_sequence(hits[-1].get("sort")))

        if seen % 500 == 0:
            conn.commit()
            logger.info(
                "%s/%s traités (%s nouveaux, %s mis à jour, %s inchangés)",
                seen,
                total,
                inserted,
                updated,
                unchanged,
            )

    conn.commit()
    return total, inserted, updated, unchanged


class ScanrExtractor(SourceExtractor[ScanrExtractConfig, ScanrExtractAdapter]):
    """Extraction ScanR — orchestrateur applicatif."""

    SOURCE = "scanr"

    def load_config(self, conn: Connection) -> ScanrExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.affiliation_ids:
            raise ExtractionConfigError(
                "aucun affiliation_id (api_ids->'scanr' vide pour le périmètre d'extraction)"
            )
        if config.credentials_missing:
            raise ExtractionConfigError(config.credentials_missing)
        return config

    def setup_logging(self, args: argparse.Namespace, config: ScanrExtractConfig) -> None:
        self.logger.info("Structures : %s", len(config.affiliation_ids))

    def extract_all(self, args: argparse.Namespace, config: ScanrExtractConfig) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, start_year=args.start_year)
        years = [args.year] if args.year else config_years
        self.logger.info("Années : %s", years)
        stats = PhaseMetrics()
        for year in years:
            if self._stop_on_tripped("années restantes sautées"):
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
            slog.info(
                "terminé : %s nouveaux, %s mis à jour, %s inchangés", inserted, updated, unchanged
            )
        return stats


__all__ = [
    "ScanrExtractor",
    "extract_year",
]
