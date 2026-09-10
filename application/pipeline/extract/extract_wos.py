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
from application.pipeline.progression import Progression
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
    avancement: Progression,
) -> tuple[int, int, int]:
    """Extrait toutes les publications d'une année.

    Retourne `(new, updated, unchanged)`."""
    data = adapter.fetch_page(year, 1, affiliations)
    if not data:
        logger.error("requête impossible")
        return 0, 0, 0

    total_count = adapter.get_records_found(data)
    if total_count == 0:
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

        counts = adapter.insert_batch(conn, records)
        conn.commit()
        total_new += counts.new
        total_updated += counts.updated
        total_unchanged += counts.unchanged
        avancement.avance(len(records))

        first_record += len(records)

        # Pause longue toutes les N pages pour laisser l'API souffler
        if page_num % _BREATHER_EVERY == 0 and first_record <= total_count:
            time.sleep(_BREATHER_SECS)

        if first_record > _WOS_FIRST_RECORD_LIMIT:
            logger.warning(
                "Limite API atteinte (%s records). Réduire la requête si des résultats manquent.",
                _WOS_FIRST_RECORD_LIMIT,
            )
            break

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
        try:
            remaining = self._adapter.check_quota()
        except Exception as e:
            self.logger.warning("Impossible de vérifier le quota : %s", e)
            return
        if remaining:
            self.logger.info("Quota annuel restant : %s records", remaining)

    def extract_all(self, args: argparse.Namespace, config: WosExtractConfig) -> PhaseMetrics:
        affiliations = config.affiliations
        years = (
            [args.year]
            if args.year
            else self._adapter.get_years(self.conn, start_year=args.start_year)
        )

        def compte(annee: int) -> int:
            try:
                return self._adapter.count(annee, affiliations)
            except Exception:
                # L'extraction de l'année rencontre la même erreur et la signale.
                return 0

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            slog = scoped_logger(self.logger, self.SOURCE, str(annee))
            try:
                new, updated, unchanged = extract_year(
                    self._adapter, self.conn, annee, affiliations, slog, avancement
                )
            except Exception as e:
                slog.error("erreur : %s — passage à la suivante", e)
                return PhaseMetrics()
            finally:
                # Pas de pause si le breaker vient de tripper : la boucle s'arrête au tour suivant.
                if annee != years[-1] and not self._breaker_tripped():
                    time.sleep(30)
            return PhaseMetrics(new=new, updated=updated, unchanged=unchanged)

        return self._extrait_par_annee(years, compte, extrait)


__all__ = [
    "WosExtractor",
    "extract_year",
]
