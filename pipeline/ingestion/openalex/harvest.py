"""Moissonnage OpenAlex : tâche `harvest.openalex`.

Interroge `/works` sur la lignée des institutions du périmètre (`authorships.institutions.lineage`), année par année ou depuis une date de modification, avec une pagination par curseur.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import as_int, as_mapping, as_sequence, as_str, at_path
from infrastructure.read_models.perimeters import get_extraction_api_ids
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

    # Identifiants OpenAlex des institutions du périmètre d'extraction.
    institution_ids: list[str]


def harvest_period(
    client: OpenalexClient,
    conn: Connection,
    institution_ids: list[str],
    logger: ScopedOrPlainLogger,
    progress: Progress,
    *,
    years: list[int],
    since: str | None = None,
) -> PhaseMetrics:
    """Moissonne les works des années `years`, modifiés depuis `since` s'il est donné, page après page."""
    metrics = PhaseMetrics()
    cursor = "*"
    total_count: int | None = None
    fetched = 0

    while True:
        data = client.fetch_page(institution_ids, years=years, cursor=cursor, since=since)
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
    """Moissonnage OpenAlex : les works des institutions du périmètre, année par année ou depuis une date."""

    SOURCE = "openalex"

    def load_config(self, conn: Connection) -> OpenalexHarvestConfig:
        institution_ids = get_extraction_api_ids(conn, "openalex")
        if not institution_ids:
            raise HarvestConfigError(
                "aucun institution_id (api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        return OpenalexHarvestConfig(institution_ids=institution_ids)

    def setup_logging(self, window: HarvestWindow, config: OpenalexHarvestConfig) -> None:
        if window.since:
            self.logger.info("Mode incrémental : documents modifiés depuis %s", window.since)

    def harvest_all(self, window: HarvestWindow, config: OpenalexHarvestConfig) -> PhaseMetrics:
        """Moissonne les works du périmètre. En mode incrémental, un seul périmètre : les works modifiés depuis la date, dans la plage d'années du mode complet. Sinon une passe par année."""
        ids = config.institution_ids
        client = self._client
        years = self._years(window)

        def harvest_step(
            progress: Progress, *, years: list[int], since: str | None = None
        ) -> PhaseMetrics:
            scope = f"depuis {since}" if since else str(years[0])
            return harvest_period(
                client,
                self.conn,
                ids,
                scoped_logger(self.logger, self.SOURCE, scope),
                progress,
                years=years,
                since=since,
            )

        if window.since:
            return self._harvest_at_once(
                client.count(ids, years=years, since=window.since),
                lambda progress: harvest_step(progress, years=years, since=window.since),
            )

        return self._harvest_by_year(
            years,
            lambda year: client.count(ids, years=[year]),
            lambda year, progress: harvest_step(progress, years=[year]),
        )
