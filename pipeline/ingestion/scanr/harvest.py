"""Moissonnage ScanR : nœud `extract.scanr`.

Interroge l'index Elasticsearch de ScanR sur les affiliations du périmètre, année par année, avec une pagination `search_after`.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    SourceExtractor,
    stage_document,
)
from pipeline.ingestion.http.api_params import SCANR_DELAY, SCANR_PER_PAGE
from pipeline.ingestion.http.http_retry import http_request_with_retry
from pipeline.ingestion.http.throttle import Throttle
from pipeline.ingestion.scanr.fields import extract_doi, extract_id
from pipeline.runtime.config import (
    get_extraction_api_ids,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression

# Nombre de documents écrits entre deux commits.
_COMMIT_EVERY = 500


@dataclass(frozen=True)
class ScanrExtractConfig:
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


class ScanrClient:
    """Client de l'index ScanR (`_search`, authentification basique), limité à un appel toutes les `SCANR_DELAY` secondes."""

    def __init__(self, base_url: str, credentials: tuple[str, str]) -> None:
        self._url = base_url
        self._auth = credentials
        self._throttle = Throttle(SCANR_DELAY)

    def fetch_page(self, query: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        """Exécute une requête Elasticsearch."""
        with self._throttle.request():
            return as_mapping(
                http_request_with_retry(
                    "POST",
                    self._url,
                    json_body=query,
                    auth=self._auth,
                    # Une page de SCANR_PER_PAGE documents peut dépasser 30 s quand le cache du cluster est vide.
                    timeout=60,
                    label="ScanR search",
                )
            )

    def count(self, year: int, affiliation_ids: list[str]) -> int:
        """Nombre de documents d'une année, lu sur un comptage exact sans document (`size=0`)."""
        query = {**build_query(year, affiliation_ids, track_total=True), "size": 0}
        return as_int(at_path(self.fetch_page(query), "hits", "total").get("value")) or 0


def extract_year(
    client: ScanrClient,
    conn: Connection,
    year: int,
    affiliation_ids: list[str],
    avancement: Progression,
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
            avancement.avance()
            doc = as_mapping(hit.get("_source"))
            scanr_id = extract_id(doc)
            if not scanr_id:
                continue
            seen += 1
            stage_document(
                conn,
                metrics,
                source="scanr",
                source_id=scanr_id,
                doi=extract_doi(doc),
                raw_data=doc,
            )
            if seen % _COMMIT_EVERY == 0:
                conn.commit()

        search_after = list(as_sequence(hits[-1].get("sort")))

    conn.commit()
    return metrics


class ScanrExtractor(SourceExtractor[ScanrExtractConfig, ScanrClient]):
    """Moissonnage ScanR : les documents des structures du périmètre, année par année."""

    SOURCE = "scanr"

    def load_config(self, conn: Connection) -> ScanrExtractConfig:
        affiliation_ids = get_extraction_api_ids(conn, "scanr")
        if not affiliation_ids:
            raise ExtractionConfigError(
                "aucun affiliation_id (api_ids->'scanr' vide pour le périmètre d'extraction)"
            )
        return ScanrExtractConfig(affiliation_ids=affiliation_ids)

    def extract_all(self, args: argparse.Namespace, config: ScanrExtractConfig) -> PhaseMetrics:
        ids = config.affiliation_ids
        client = self._client
        years = self._years(args)
        return self._extrait_par_annee(
            years,
            lambda annee: client.count(annee, ids),
            lambda annee, avancement: extract_year(client, self.conn, annee, ids, avancement),
        )
