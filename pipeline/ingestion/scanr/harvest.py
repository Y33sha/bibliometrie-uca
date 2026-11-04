"""Moissonnage ScanR : tâche `harvest.scanr`.

La requête à l'index Elasticsearch de ScanR cible les affiliations du périmètre, année par année. La pagination suit `search_after`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import Connection

from domain.types import JsonValue
from pipeline.ingestion.api_params import SCANR_PER_PAGE
from pipeline.ingestion.common.harvester import (
    HarvestWindow,
    SourceHarvester,
    stage_pages,
)
from pipeline.ingestion.scanr.api import ScanrClient, hits_page, search_after
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress

_COMMIT_EVERY = 500
"""Nombre de documents écrits entre deux commits."""


def build_query(
    year: int,
    affiliation_ids: list[str],
    search_after: Sequence[JsonValue] | None = None,
    *,
    track_total: bool = False,
) -> Mapping[str, JsonValue]:
    """Construit la requête Elasticsearch d'une page.

    Les clauses sont en contexte `filter` : un `term` sur l'année et un `terms` sur les affiliations. Ce contexte se passe de `_score`, et le cluster le met en cache : il répond neuf fois plus vite que l'équivalent `must`/`should` (1 s contre 9,5 s pour une page de 200). Le tri sur `id.keyword` sert la pagination `search_after`.

    `track_total` demande le comptage exact (`track_total_hits`), consommé seulement par `count`. Les pages le coupent : Elasticsearch recompterait sinon tous les résultats à chaque page.
    """
    query: dict[str, JsonValue] = {
        "size": SCANR_PER_PAGE,
        "track_total_hits": track_total,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"year": year}},
                    {"terms": {"affiliations.id.keyword": affiliation_ids}},
                ]
            }
        },
        "sort": [{"id.keyword": "asc"}],
    }
    if search_after:
        query["search_after"] = list(search_after)
    return query


def harvest_year(
    client: ScanrClient,
    conn: Connection,
    year: int,
    affiliation_ids: list[str],
    progress: Progress,
    metrics: PhaseMetrics,
) -> None:
    """Moissonne les documents d'une année, page après page, et compte les écritures dans `metrics`."""
    stage_pages(
        conn,
        metrics,
        "scanr",
        lambda token: hits_page(
            client.fetch_page(build_query(year, affiliation_ids, search_after(token)))
        ),
        progress=progress,
    )


class ScanrHarvester(SourceHarvester[ScanrClient]):
    """Moissonnage ScanR des documents des structures du périmètre, année par année."""

    SOURCE = "scanr"
    MISSING_API_IDS = "aucun affiliation_id"

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        ids = self._api_ids()
        client = self._client
        years = self._years(window)
        return self._harvest_by_year(
            years,
            lambda year: client.count(build_query(year, ids)),
            lambda year, progress, metrics: harvest_year(
                client, self.conn, year, ids, progress, metrics
            ),
        )
