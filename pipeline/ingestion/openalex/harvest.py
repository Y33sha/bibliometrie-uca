"""Moissonnage OpenAlex : tâche `harvest.openalex`.

La requête `/works` cible la lignée des institutions du périmètre, année par année. La pagination suit un curseur.
"""

from __future__ import annotations

from sqlalchemy import Connection

from domain.types import as_int, as_mapping, as_sequence, as_str, at_path
from pipeline.ingestion.common.harvester import (
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.openalex.api import OpenalexClient
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger, scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress


def harvest_period(
    client: OpenalexClient,
    conn: Connection,
    institution_ids: list[str],
    logger: ScopedOrPlainLogger,
    progress: Progress,
    metrics: PhaseMetrics,
    *,
    years: list[int],
) -> None:
    """Moissonne les works des années `years`, page après page, et compte les écritures dans `metrics`."""
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


class OpenalexHarvester(SourceHarvester[OpenalexClient]):
    """Moissonnage OpenAlex des works des institutions du périmètre, année par année."""

    SOURCE = "openalex"
    MISSING_API_IDS = "aucun institution_id"

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        """Moissonne les works du périmètre, une passe par année."""
        ids = self._api_ids()
        client = self._client

        def harvest_step(year: int, progress: Progress, metrics: PhaseMetrics) -> None:
            harvest_period(
                client,
                self.conn,
                ids,
                scoped_logger(self.logger, self.SOURCE, str(year)),
                progress,
                metrics,
                years=[year],
            )

        return self._harvest_by_year(
            self._years(window), lambda year: client.count(ids, years=[year]), harvest_step
        )
