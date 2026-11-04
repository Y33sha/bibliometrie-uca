"""Moissonnage OpenAlex : tâche `harvest.openalex`.

La requête `/works` cible la lignée des institutions du périmètre, année par année. La pagination suit un curseur.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import as_int, as_mapping, as_sequence, as_str, at_path
from infrastructure.read_models.perimeters.queries import get_extraction_api_ids
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.openalex.api import OpenalexClient
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger, scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress


@dataclass(frozen=True)
class OpenalexHarvestConfig:
    """Configuration du moissonnage OpenAlex, lue en base."""

    institution_ids: list[str]
    """Identifiants OpenAlex des institutions du périmètre de moissonnage."""


def harvest_period(
    client: OpenalexClient,
    conn: Connection,
    institution_ids: list[str],
    logger: ScopedOrPlainLogger,
    progress: Progress,
    *,
    years: list[int],
) -> PhaseMetrics:
    """Moissonne les works des années `years`, page après page."""
    metrics = PhaseMetrics()
    cursor = "*"
    total_count: int | None = None
    fetched = 0

    while True:
        data = client.fetch_page(institution_ids, years=years, cursor=cursor)
        if total_count is None:
            total_count = as_int(at_path(data, "meta").get("count")) or 0

        works = [as_mapping(r) for r in as_sequence(data.get("results"))]
        if not works:
            break

        for work in works:
            stage_document(conn, metrics, source="openalex", record=work)
        conn.commit()
        fetched += len(works)
        progress.advance(len(works))

        next_cursor = as_str(at_path(data, "meta").get("next_cursor"))
        if not next_cursor:
            break
        cursor = next_cursor

    if total_count and fetched < total_count:
        logger.warning("%s documents non récupérés sur %s", total_count - fetched, total_count)
    return metrics


class OpenalexHarvester(SourceHarvester[OpenalexHarvestConfig, OpenalexClient]):
    """Moissonnage OpenAlex des works des institutions du périmètre, année par année."""

    SOURCE = "openalex"

    def load_config(self, conn: Connection) -> OpenalexHarvestConfig:
        institution_ids = get_extraction_api_ids(conn, "openalex")
        if not institution_ids:
            raise HarvestConfigError(
                "aucun institution_id (api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        return OpenalexHarvestConfig(institution_ids=institution_ids)

    def harvest_all(self, window: HarvestWindow, config: OpenalexHarvestConfig) -> PhaseMetrics:
        """Moissonne les works du périmètre, une passe par année."""
        ids = config.institution_ids
        client = self._client

        def harvest_step(year: int, progress: Progress) -> PhaseMetrics:
            return harvest_period(
                client,
                self.conn,
                ids,
                scoped_logger(self.logger, self.SOURCE, str(year)),
                progress,
                years=[year],
            )

        return self._harvest_by_year(
            self._years(window), lambda year: client.count(ids, years=[year]), harvest_step
        )
