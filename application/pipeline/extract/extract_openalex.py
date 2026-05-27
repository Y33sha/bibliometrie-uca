"""Orchestrateur d'extraction OpenAlex.

Pilote l'extraction par année (ou par `since` en mode incrémental) via
le cursor OpenAlex. Le détail HTTP/SQL est délégué à
`OpenalexExtractAdapter`.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import Connection

from application.pipeline.extract.base import ExtractionConfigError, SourceExtractor
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.openalex import (
    OpenalexExtractAdapter,
    OpenalexExtractConfig,
)
from application.ports.pipeline.staging import StagingQueries


def extract_year(
    adapter: OpenalexExtractAdapter,
    conn: Connection,
    existing_ids: set[str],
    institution_ids: list[str],
    logger: logging.Logger,
    *,
    year: int | None = None,
    since: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Extrait des publications OpenAlex par année ou par date de modification.

    Retourne (nouveaux, mis_a_jour) — ventilation calculée par l'adapter via `xmax`.
    """
    cursor = "*"
    total_fetched = 0
    total_new = 0
    total_updated = 0
    page_num = 0

    first_page = adapter.fetch_page(institution_ids, year=year, cursor=cursor, since=since)
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
            data = adapter.fetch_page(institution_ids, year=year, cursor=cursor, since=since)

        results = data.get("results", [])
        if not results:
            break

        # Maintenu pour cohérence avec les autres extracteurs : on entretient
        # `existing_ids` pour que les phases suivantes y aient accès.
        for work in results:
            existing_ids.add(adapter.extract_id(work))

        counts = adapter.insert_batch(conn, list(results))
        conn.commit()
        total_new += counts.new
        total_updated += counts.updated

        total_fetched += len(results)
        logger.info(
            f"  Page {page_num} : {len(results)} works — "
            f"{counts.new} nouveaux, {counts.updated} mis à jour "
            f"({total_fetched}/{total_count})"
        )

        next_cursor = data["meta"].get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

    logger.info(
        f"Année {year} terminée : {total_new} nouveaux, {total_updated} mis à jour "
        f"(sur {total_fetched} récupérés, {total_count} sur OpenAlex)"
    )
    return total_new, total_updated


class OpenalexExtractor(SourceExtractor[OpenalexExtractConfig]):
    """Extraction OpenAlex — orchestrateur applicatif."""

    SOURCE = "openalex"
    DESCRIPTION = "Extraction OpenAlex → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging: StagingQueries,
        adapter: OpenalexExtractAdapter,
    ) -> None:
        super().__init__(conn, logger, staging)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )
        parser.add_argument(
            "--since",
            help="Date ISO (YYYY-MM-DD) : ne récupérer que les documents modifiés depuis cette date",
        )

    def load_config(self, conn: Connection) -> OpenalexExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.institution_ids:
            raise ExtractionConfigError(
                "aucun institution_id OpenAlex configuré "
                "(structures.api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> None:
        self.logger.info(
            f"Institutions OpenAlex : {', '.join(config.institution_ids)} (lineage OR)"
        )
        if args.since:
            self.logger.info(f"Mode incrémental : documents modifiés depuis {args.since}")

    def extract_all(
        self,
        args: argparse.Namespace,
        config: OpenalexExtractConfig,
        existing_ids: set[str],
    ) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years
        if not args.since:
            self.logger.info(f"Années : {years}")

        stats = PhaseMetrics()
        if args.since:
            year_new, year_updated = extract_year(
                self._adapter,
                self.conn,
                existing_ids,
                config.institution_ids,
                self.logger,
                since=args.since,
                dry_run=args.dry_run,
            )
            stats.add(new=year_new, updated=year_updated)
        else:
            for year in years:
                year_new, year_updated = extract_year(
                    self._adapter,
                    self.conn,
                    existing_ids,
                    config.institution_ids,
                    self.logger,
                    year=year,
                    dry_run=args.dry_run,
                )
                stats.add(new=year_new, updated=year_updated)
        return stats


__all__ = [
    "OpenalexExtractor",
    "extract_year",
]
