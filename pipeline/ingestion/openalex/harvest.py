"""Moissonnage OpenAlex : tâche `harvest.openalex`.

La requête `/works` cible la lignée des institutions du périmètre, année par année. La pagination suit un curseur.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from pipeline.ingestion.common.harvester import (
    HarvestWindow,
    SourceHarvester,
    stage_pages,
    year_range,
)
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.openalex.api import OpenalexClient, works_page
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress
from pipeline.runtime.observability.signals import signal_harvest_incomplete

INCOMPLETE_TOLERANCE = 0.01
"""Part des works annoncés qui peut manquer sans signal. Un écart plus faible est seulement journalisé."""


def harvest_period(
    client: OpenalexClient,
    conn: Connection,
    institution_ids: list[str],
    logger: logging.Logger,
    progress: Progress,
    metrics: PhaseMetrics,
    *,
    years: list[int],
) -> None:
    """Moissonne les works des années `years`, page après page, et compte les écritures dans `metrics`.

    Moins de works reçus qu'annoncés par la première page : l'écart est journalisé avec le point d'arrêt de la pagination, et émet un signal `harvest_incomplete` au-delà de `INCOMPLETE_TOLERANCE`.
    """
    announced: int | None = None
    # Dernière page reçue et curseur demandé pour elle : le point d'arrêt de la pagination.
    requested = "*"
    page = Page([], None)

    def fetch(cursor: str | None) -> Page:
        nonlocal announced, requested, page
        requested = cursor or "*"
        page = works_page(client.fetch_page(institution_ids, years=years, cursor=requested))
        if cursor is None:
            announced = page.total
        return page

    received = stage_pages(conn, metrics, "openalex", fetch, progress=progress)
    if not announced or received >= announced:
        return
    stop = (
        f"page vide au curseur {requested}"
        if not page.records
        else f"page de {len(page.records)} works sans curseur suivant, au curseur {requested}"
    )
    scope = year_range(sorted(years))
    scoped_logger(logger, "openalex", scope).warning(
        "%d works reçus sur %d annoncés, pagination arrêtée : %s", received, announced, stop
    )
    if announced - received > announced * INCOMPLETE_TOLERANCE:
        signal_harvest_incomplete(
            metrics, "openalex", scope, received=received, announced=announced
        )


class OpenalexHarvester(SourceHarvester[OpenalexClient]):
    """Moissonnage OpenAlex des works des institutions du périmètre, année par année."""

    SOURCE = "openalex"
    MISSING_API_IDS = "aucun institution_id"

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        """Moissonne les works du périmètre, une passe par année."""
        ids = self._api_ids()
        client = self._client

        def harvest_step(year: int, progress: Progress, metrics: PhaseMetrics) -> None:
            harvest_period(client, self.conn, ids, self.logger, progress, metrics, years=[year])

        return self._harvest_by_year(
            self._years(window), lambda year: client.count(ids, years=[year]), harvest_step
        )
