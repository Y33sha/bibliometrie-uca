"""Moissonnage Web of Science : tâche `harvest.wos`.

La requête à l'API WoS Expanded cible les affiliations du périmètre (`OG=`), année par année. La pagination refait la recherche avec `firstRecord` à chaque page : la pagination par `queryId` renvoie des pages vides.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure.read_models.perimeters.queries import get_extraction_api_ids
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.wos.api import WosClient, get_records, get_records_found
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger, scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress

# Pause longue toutes les `_BREATHER_EVERY` pages.
_BREATHER_EVERY = 10
_BREATHER_SECS = 15
# Pause entre deux années.
_BETWEEN_YEARS_SECS = 30
# Plafond de l'API : `firstRecord` ne dépasse pas 100 000 sur une requête.
_WOS_FIRST_RECORD_LIMIT = 100_000


@dataclass(frozen=True)
class WosHarvestConfig:
    """Configuration du moissonnage WoS, lue en base."""

    affiliations: list[str]
    """Variantes d'affiliation (Organization-Enhanced) du périmètre de moissonnage."""


def harvest_year(
    client: WosClient,
    conn: Connection,
    year: int,
    affiliations: list[str],
    logger: ScopedOrPlainLogger,
    progress: Progress,
) -> PhaseMetrics:
    """Moissonne les records d'une année, page après page.

    Une page vide est retentée après une pause ; trois pages vides de suite arrêtent l'année.
    """
    metrics = PhaseMetrics()
    data = client.fetch_page(year, 1, affiliations)
    if not data:
        logger.error("requête impossible")
        return metrics

    total_count = get_records_found(data)
    first_record = 1
    page_num = 0
    consecutive_failures = 0

    while first_record <= total_count:
        records = get_records(data)
        if not records:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.error("3 pages vides consécutives à firstRecord=%s, arrêt", first_record)
                break
            logger.warning(
                "Page vide à firstRecord=%s, nouvelle tentative après pause...", first_record
            )
            time.sleep(5)
            data = client.fetch_page(year, first_record, affiliations)
            continue

        consecutive_failures = 0
        page_num += 1

        for record in records:
            stage_document(conn, metrics, source="wos", record=record)
        conn.commit()
        progress.advance(len(records))
        first_record += len(records)

        if first_record > _WOS_FIRST_RECORD_LIMIT:
            logger.warning(
                "Limite API atteinte (%s records). Réduire la requête si des résultats manquent.",
                _WOS_FIRST_RECORD_LIMIT,
            )
            break
        if first_record <= total_count:
            if page_num % _BREATHER_EVERY == 0:
                time.sleep(_BREATHER_SECS)
            data = client.fetch_page(year, first_record, affiliations)

    return metrics


class WosHarvester(SourceHarvester[WosHarvestConfig, WosClient]):
    """Moissonnage WoS des records des affiliations du périmètre, année par année.

    Une erreur sur une année est journalisée, et le moissonnage passe à la suivante.
    """

    SOURCE = "wos"

    def load_config(self, conn: Connection) -> WosHarvestConfig:
        affiliations = get_extraction_api_ids(conn, "wos")
        if not affiliations:
            raise HarvestConfigError(
                "aucune affiliation (api_ids->'wos' vide pour le périmètre d'extraction)"
            )
        return WosHarvestConfig(affiliations=affiliations)

    def setup_logging(self, window: HarvestWindow, config: WosHarvestConfig) -> None:
        try:
            remaining = self._client.check_quota()
        except Exception as e:
            self.logger.warning("Impossible de vérifier le quota : %s", e)
            return
        if remaining:
            self.logger.info("Quota annuel restant : %s records", remaining)

    def harvest_all(self, window: HarvestWindow, config: WosHarvestConfig) -> PhaseMetrics:
        affiliations = config.affiliations
        client = self._client
        years = self._years(window)

        def count_year(year: int) -> int:
            try:
                return client.count(year, affiliations)
            except SourceUnavailableError:
                raise
            except Exception:
                # Le moissonnage de l'année rencontre la même erreur et la signale.
                return 0

        def harvest_step(year: int, progress: Progress) -> PhaseMetrics:
            slog = scoped_logger(self.logger, self.SOURCE, str(year))
            try:
                metrics = harvest_year(client, self.conn, year, affiliations, slog, progress)
            except SourceUnavailableError:
                raise
            except Exception as e:
                slog.error("erreur : %s — passage à la suivante", e)
                metrics = PhaseMetrics()
            if year != years[-1]:
                time.sleep(_BETWEEN_YEARS_SECS)
            return metrics

        return self._harvest_by_year(years, count_year, harvest_step)
