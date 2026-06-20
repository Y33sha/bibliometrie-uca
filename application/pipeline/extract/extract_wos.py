"""Orchestrateur d'extraction WoS.

Pilote l'extraction par année via la pagination `firstRecord` (queryId
non fiable côté Clarivate). Le détail HTTP/SQL est délégué à
`WosExtractAdapter`.
"""

from __future__ import annotations

import argparse
import logging
import time

from sqlalchemy import Connection

from application.pipeline.extract.base import ExtractionConfigError, SourceExtractor
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.wos import WosExtractAdapter, WosExtractConfig
from application.ports.pipeline.staging import StagingQueries

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
    logger: logging.Logger,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait toutes les publications d'une année.

    Retourne `(new, updated, unchanged)`."""
    logger.info(f"Requête WoS : {adapter.build_query(year, affiliations)}")

    data = adapter.fetch_page(year, 1, affiliations)
    if not data:
        logger.error(f"Impossible d'exécuter la requête pour {year}")
        return 0, 0, 0

    total_count = adapter.get_records_found(data)
    logger.info(f"Année {year} : {total_count} records trouvés")

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
                logger.error(
                    f"3 pages vides consécutives à firstRecord={first_record}, "
                    f"arrêt de l'année {year}"
                )
                break
            logger.warning(
                f"Page vide à firstRecord={first_record}, nouvelle tentative après pause..."
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
            f"  Page {page_num} : {len(records)} records, "
            f"{counts.new} nouveaux, {counts.updated} mis à jour, {counts.unchanged} inchangés "
            f"({min(first_record + len(records) - 1, total_count)}/{total_count})"
        )

        first_record += len(records)

        # Pause longue toutes les N pages pour laisser l'API souffler
        if page_num % _BREATHER_EVERY == 0 and first_record <= total_count:
            logger.info(f"  Pause de {_BREATHER_SECS}s (toutes les {_BREATHER_EVERY} pages)...")
            time.sleep(_BREATHER_SECS)

        if first_record > _WOS_FIRST_RECORD_LIMIT:
            logger.warning(
                f"Limite API atteinte ({_WOS_FIRST_RECORD_LIMIT} records). "
                "Réduire la requête si des résultats manquent."
            )
            break

    logger.info(
        f"Année {year} terminée : {total_new} nouveaux, {total_updated} mis à jour, "
        f"{total_unchanged} inchangés sur {total_count} trouvés"
    )
    return total_new, total_updated, total_unchanged


class WosExtractor(SourceExtractor[WosExtractConfig]):
    """Extraction WoS — orchestrateur applicatif."""

    SOURCE = "wos"
    DESCRIPTION = "Extraction WoS → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging: StagingQueries,
        adapter: WosExtractAdapter,
    ) -> None:
        super().__init__(conn, logger, staging)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )

    def load_config(self, conn: Connection) -> WosExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.affiliations:
            raise ExtractionConfigError(
                "aucune affiliation WoS configurée "
                "(structures.api_ids->'wos' vide pour le périmètre d'extraction)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: WosExtractConfig) -> None:
        self.logger.info(f"Affiliations : {config.affiliations}")
        try:
            remaining = self._adapter.check_quota()
        except Exception as e:
            self.logger.warning(f"Impossible de vérifier le quota : {e}")
            return
        if remaining:
            self.logger.info(f"Quota annuel restant : {remaining} records")

    def extract_all(self, args: argparse.Namespace, config: WosExtractConfig) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years
        self.logger.info(f"Années : {years}")

        stats = PhaseMetrics()
        for i, year in enumerate(years):
            if self._breaker_tripped():
                self.logger.warning(
                    "WoS à bout (429/5xx répétés) — années restantes sautées (retry au prochain run)"
                )
                break
            try:
                new, updated, unchanged = extract_year(
                    self._adapter,
                    self.conn,
                    year,
                    config.affiliations,
                    self.logger,
                    dry_run=args.dry_run,
                )
                stats.add(new=new, updated=updated, unchanged=unchanged)
            except Exception as e:
                self.logger.error(f"Erreur sur l'année {year} : {e} — passage à la suivante")
            # Pas de pause si le breaker vient de tripper : la boucle s'arrête au tour suivant.
            if i < len(years) - 1 and not self._breaker_tripped():
                self.logger.info("Pause de 30s avant l'année suivante...")
                time.sleep(30)
        return stats

    def log_summary(self, stats: PhaseMetrics, args: argparse.Namespace) -> None:
        self.logger.info(f"=== Terminé : {stats.as_summary()} ===")


__all__ = [
    "WosExtractor",
    "extract_year",
]
