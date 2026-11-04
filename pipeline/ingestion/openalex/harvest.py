"""Moissonnage OpenAlex : tâche `harvest.openalex`.

La requête `/works` cible la lignée des institutions du périmètre, année par année. La pagination suit un curseur.
"""

from __future__ import annotations

from sqlalchemy import Connection

from pipeline.ingestion.common.harvester import (
    HarvestWindow,
    SourceHarvester,
    stage_pages,
)
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.openalex.api import OpenalexClient, works_page
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
    totals: list[int | None] = []

    def fetch(cursor: str | None) -> Page:
        page = works_page(client.fetch_page(institution_ids, years=years, cursor=cursor or "*"))
        totals.append(page.total)
        return page

    fetched = stage_pages(conn, metrics, "openalex", fetch, progress=progress)
    total_count = totals[0] if totals else None
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
