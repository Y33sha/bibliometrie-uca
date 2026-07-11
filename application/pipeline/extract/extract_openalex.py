"""Orchestrateur d'extraction OpenAlex.

Pilote l'extraction par année (ou par `since` en mode incrémental) via le cursor OpenAlex. Le détail HTTP/SQL est délégué à `OpenalexExtractAdapter`.
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
from application.ports.pipeline.extract.openalex import (
    OpenalexExtractAdapter,
    OpenalexExtractConfig,
)


def extract_year(
    adapter: OpenalexExtractAdapter,
    conn: Connection,
    institution_ids: list[str],
    logger: ExtractLogger,
    *,
    year: int | None = None,
    since: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait des publications OpenAlex par année ou par date de modification.

    Retourne (nouveaux, mis_a_jour, inchangés) — ventilation calculée par l'adapter via `xmax` (insert) + comparaison de hash (changed).
    """
    cursor = "*"
    total_fetched = 0
    total_new = 0
    total_updated = 0
    total_unchanged = 0
    page_num = 0

    first_page = adapter.fetch_page(institution_ids, year=year, cursor=cursor, since=since)
    total_count = first_page["meta"]["count"]
    logger.info(f"{total_count} works trouvés")

    if dry_run:
        return 0, 0, 0

    while True:
        page_num += 1

        if page_num == 1:
            data = first_page
        else:
            data = adapter.fetch_page(institution_ids, year=year, cursor=cursor, since=since)

        results = data.get("results", [])
        if not results:
            break

        counts = adapter.insert_batch(conn, list(results))
        conn.commit()
        total_new += counts.new
        total_updated += counts.updated
        total_unchanged += counts.unchanged

        total_fetched += len(results)
        logger.info(
            f"page {page_num} : {len(results)} works — "
            f"{counts.new} nouveaux, {counts.updated} mis à jour, {counts.unchanged} inchangés "
            f"({total_fetched}/{total_count})"
        )

        next_cursor = data["meta"].get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

    logger.info(
        f"terminé : {total_new} nouveaux, {total_updated} mis à jour, "
        f"{total_unchanged} inchangés (sur {total_fetched} récupérés, {total_count} au total)"
    )
    return total_new, total_updated, total_unchanged


class OpenalexExtractor(SourceExtractor[OpenalexExtractConfig]):
    """Extraction OpenAlex — orchestrateur applicatif."""

    SOURCE = "openalex"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        adapter: OpenalexExtractAdapter,
    ) -> None:
        super().__init__(conn, logger)
        self._adapter = adapter

    def load_config(self, conn: Connection) -> OpenalexExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.institution_ids:
            raise ExtractionConfigError(
                "aucun institution_id (api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        if config.credentials_missing:
            raise ExtractionConfigError(config.credentials_missing)
        return config

    def setup_logging(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> None:
        self.logger.info(
            f"Institutions OpenAlex : {', '.join(config.institution_ids)} (lineage OR)"
        )
        if args.since:
            self.logger.info(f"Mode incrémental : documents modifiés depuis {args.since}")

    def extract_all(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, start_year=args.start_year)
        years = [args.year] if args.year else config_years
        if not args.since:
            self.logger.info(f"Années : {years}")

        stats = PhaseMetrics()
        if args.since:
            year_new, year_updated, year_unchanged = extract_year(
                self._adapter,
                self.conn,
                config.institution_ids,
                scoped_logger(self.logger, self.SOURCE, f"depuis {args.since}"),
                since=args.since,
                dry_run=args.dry_run,
            )
            stats.add(new=year_new, updated=year_updated, unchanged=year_unchanged)
        else:
            for year in years:
                if self._breaker_tripped():
                    self.logger.warning(
                        "OpenAlex à bout (429/5xx répétés) — années restantes sautées"
                        " (retry au prochain run)"
                    )
                    break
                year_new, year_updated, year_unchanged = extract_year(
                    self._adapter,
                    self.conn,
                    config.institution_ids,
                    scoped_logger(self.logger, self.SOURCE, str(year)),
                    year=year,
                    dry_run=args.dry_run,
                )
                stats.add(new=year_new, updated=year_updated, unchanged=year_unchanged)
        return stats


__all__ = [
    "OpenalexExtractor",
    "extract_year",
]
