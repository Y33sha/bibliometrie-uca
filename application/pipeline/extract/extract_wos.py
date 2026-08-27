"""Orchestrateur d'extraction WoS.

Pilote l'extraction par année via la pagination `firstRecord` (queryId non fiable côté Clarivate). Le détail HTTP/SQL est délégué à `WosExtractAdapter`.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import Connection

from application.pipeline.extract.base import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.wos import WosExtractAdapter, WosExtractConfig

# Constantes techniques de l'orchestration (pas spécifiques à l'API).
_BREATHER_EVERY = 10  # pause longue toutes les N pages
_BREATHER_SECS = 15  # durée de la pause longue (secondes)
# Limite WoS : firstRecord ne peut pas dépasser 100 000 sur une requête.
_WOS_FIRST_RECORD_LIMIT = 100_000


def extract_year(
    adapter: WosExtractAdapter,
    conn: Connection,
    year: int,
    affiliations: list[str],
    logger: ExtractLogger,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait toutes les publications d'une année.

    Retourne `(new, updated, unchanged)`."""
    logger.info("requête : %s", adapter.build_query(year, affiliations))

    data = adapter.fetch_page(year, 1, affiliations)
    if not data:
        logger.error("requête impossible")
        return 0, 0, 0

    total_count = adapter.get_records_found(data)
    logger.info("%s records trouvés", total_count)

    if dry_run or total_count == 0:
        return 0, 0, 0

    total_new = 0
    total_updated = 0
    total_unchanged = 0
    first_record = 1
    page_num = 0
    consecutive_failures = 0

    while first_record <= total_count:
        if first_record > 1:
            data = adapter.fetch_page(year, first_record, affiliations)

        records = adapter.get_records(data)
        if not records:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.error("3 pages vides consécutives à firstRecord=%s, arrêt", first_record)
                break
            logger.warning(
                "Page vide à firstRecord=%s, nouvelle tentative après pause...", first_record
            )
            time.sleep(5)
            continue

        consecutive_failures = 0
        page_num += 1

        if records:
            counts = adapter.insert_batch(conn, records)
            conn.commit()
            total_new += counts.new
            total_updated += counts.updated
            total_unchanged += counts.unchanged

        logger.info(
            "page %s : %s records, %s nouveaux, %s mis à jour, %s inchangés (%s/%s)",
            page_num,
            len(records),
            counts.new,
            counts.updated,
            counts.unchanged,
            min(first_record + len(records) - 1, total_count),
            total_count,
        )

        first_record += len(records)

        # Pause longue toutes les N pages pour laisser l'API souffler
        if page_num % _BREATHER_EVERY == 0 and first_record <= total_count:
            logger.info("pause de %ss (toutes les %s pages)…", _BREATHER_SECS, _BREATHER_EVERY)
            time.sleep(_BREATHER_SECS)

        if first_record > _WOS_FIRST_RECORD_LIMIT:
            logger.warning(
                "Limite API atteinte (%s records). Réduire la requête si des résultats manquent.",
                _WOS_FIRST_RECORD_LIMIT,
            )
            break

    logger.info(
        "terminé : %s nouveaux, %s mis à jour, %s inchangés sur %s trouvés",
        total_new,
        total_updated,
        total_unchanged,
        total_count,
    )
    return total_new, total_updated, total_unchanged


class WosExtractor(SourceExtractor[WosExtractConfig, WosExtractAdapter]):
    """Extraction WoS — orchestrateur applicatif."""

    SOURCE = "wos"

    def load_config(self, conn: Connection) -> WosExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.affiliations:
            raise ExtractionConfigError(
                "aucune affiliation (api_ids->'wos' vide pour le périmètre d'extraction)"
            )
        if config.credentials_missing:
            raise ExtractionConfigError(config.credentials_missing)
        return config

    def setup_logging(self, args: argparse.Namespace, config: WosExtractConfig) -> None:
        self.logger.info("Affiliations : %s", config.affiliations)
        try:
            remaining = self._adapter.check_quota()
        except Exception as e:
            self.logger.warning("Impossible de vérifier le quota : %s", e)
            return
        if remaining:
            self.logger.info("Quota annuel restant : %s records", remaining)

    def extract_all(self, args: argparse.Namespace, config: WosExtractConfig) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, start_year=args.start_year)
        years = [args.year] if args.year else config_years
        self.logger.info("Années : %s", years)

        stats = PhaseMetrics()
        for i, year in enumerate(years):
            if self._stop_on_tripped("années restantes sautées"):
                break
            slog = scoped_logger(self.logger, self.SOURCE, str(year))
            try:
                new, updated, unchanged = extract_year(
                    self._adapter,
                    self.conn,
                    year,
                    config.affiliations,
                    slog,
                    dry_run=args.dry_run,
                )
                stats.add(new=new, updated=updated, unchanged=unchanged)
            except Exception as e:
                slog.error("erreur : %s — passage à la suivante", e)
            # Pas de pause si le breaker vient de tripper : la boucle s'arrête au tour suivant.
            if i < len(years) - 1 and not self._breaker_tripped():
                self.logger.info("Pause de 30s avant l'année suivante...")
                time.sleep(30)
        return stats


__all__ = [
    "WosExtractor",
    "extract_year",
]
