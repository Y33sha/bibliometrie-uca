"""Moissonnage ScanR : tâche `harvest.scanr`.

Interroge l'index Elasticsearch de ScanR sur les affiliations du périmètre, année par année, avec une pagination `search_after`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import JsonValue, as_mapping, as_sequence, at_path
from infrastructure.read_models.perimeters.queries import get_extraction_api_ids
from pipeline.ingestion.api_params import SCANR_PER_PAGE
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.scanr.api import ScanrClient
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress

# Nombre de documents écrits entre deux commits.
_COMMIT_EVERY = 500


@dataclass(frozen=True)
class ScanrHarvestConfig:
    """Configuration du moissonnage ScanR, lue en base."""

    # Identifiants ScanR des structures du périmètre d'extraction.
    affiliation_ids: list[str]


def build_query(
    year: int,
    affiliation_ids: list[str],
    search_after: Sequence[JsonValue] | None = None,
    *,
    track_total: bool = False,
) -> Mapping[str, JsonValue]:
    """Requête Elasticsearch d'une page.

    Tout est en **contexte `filter`** : un `term` sur l'année et un `terms` sur les affiliations (au moins une de la liste). Le contexte `filter` ne calcule aucun `_score` et est mis en cache par le cluster : mesuré ~9× plus rapide que l'équivalent `must`/`should` (≈1 s contre ≈9,5 s par page de 200), pour un résultat identique. Le tri sur `id.keyword` permet la pagination `search_after`.

    `track_total` demande le comptage exact (`track_total_hits`), que seul `count` consomme. Les pages le coupent : Elasticsearch recompterait sinon tous les résultats à chaque page.
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
) -> PhaseMetrics:
    """Moissonne les documents d'une année, page après page."""
    metrics = PhaseMetrics()
    search_after: list[JsonValue] | None = None
    seen = 0

    while True:
        data = client.fetch_page(build_query(year, affiliation_ids, search_after))
        hits = [as_mapping(h) for h in as_sequence(at_path(data, "hits").get("hits"))]
        if not hits:
            break

        for hit in hits:
            progress.advance()
            doc = as_mapping(hit.get("_source"))
            if not stage_document(conn, metrics, source="scanr", record=doc):
                continue
            seen += 1
            if seen % _COMMIT_EVERY == 0:
                conn.commit()

        search_after = list(as_sequence(hits[-1].get("sort")))

    conn.commit()
    return metrics


class ScanrHarvester(SourceHarvester[ScanrHarvestConfig, ScanrClient]):
    """Moissonnage ScanR : les documents des structures du périmètre, année par année."""

    SOURCE = "scanr"

    def load_config(self, conn: Connection) -> ScanrHarvestConfig:
        affiliation_ids = get_extraction_api_ids(conn, "scanr")
        if not affiliation_ids:
            raise HarvestConfigError(
                "aucun affiliation_id (api_ids->'scanr' vide pour le périmètre d'extraction)"
            )
        return ScanrHarvestConfig(affiliation_ids=affiliation_ids)

    def harvest_all(self, window: HarvestWindow, config: ScanrHarvestConfig) -> PhaseMetrics:
        ids = config.affiliation_ids
        client = self._client
        years = self._years(window)
        return self._harvest_by_year(
            years,
            lambda year: client.count(build_query(year, ids)),
            lambda year, progress: harvest_year(client, self.conn, year, ids, progress),
        )
