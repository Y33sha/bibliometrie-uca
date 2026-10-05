"""Adapter DataCite pour la phase extract : moissonnage par mots-clés d'affiliation.

Implémente le port `application.ports.pipeline.extract.datacite.DataciteExtractAdapter`. Interroge `GET /dois` par année de publication, sur les affiliations des créateurs (`creators.affiliation.name`), avec une pagination par curseur. Les mots-clés viennent de `structures.api_ids->'datacite'` pour le périmètre d'extraction. La phase `affiliations` tranche ensuite quelles signatures relèvent du périmètre.

Les paramètres de requête sont ceux de la phase `fetch_missing` (affiliations en chaînes) : un même DOI garde la même forme, quel que soit le chemin qui le ramène.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import Connection

from application.ports.pipeline.extract._common import BatchInsertCounts, UpsertOutcome
from application.ports.pipeline.extract.datacite import (
    DataciteExtractAdapter,
    DataciteExtractConfig,
    DatacitePage,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_extraction_api_ids, get_years
from infrastructure.sources.datacite.nodes import api_headers, record_doi
from infrastructure.sources.http_retry import http_request_with_retry

# Plafond de l'API DataCite pour la taille d'une page.
_PAGE_SIZE = 1000


def build_query(year: int, keywords: list[str]) -> str:
    """Requête `query` DataCite : DOI publiés l'année `year` dont une affiliation de créateur contient l'un des mots-clés, chacun cherché comme expression exacte."""
    clauses = " OR ".join(
        'creators.affiliation.name:"{}"'.format(k.replace("\\", "\\\\").replace('"', '\\"'))
        for k in keywords
    )
    return f"publicationYear:{year} AND ({clauses})"


class PgDataciteExtractAdapter(DataciteExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `DataciteExtractAdapter`."""

    def __init__(self, base_url: str = API_BASE_URLS["datacite"]) -> None:
        self._url = f"{base_url}/dois"
        self._headers = api_headers()

    def _get(
        self, url: str, params: Mapping[str, str | int] | None, label: str
    ) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry(
                "GET", url, params=params, headers=self._headers, timeout=180, label=label
            )
        )

    def load_config(self, conn: Connection) -> DataciteExtractConfig:
        return DataciteExtractConfig(keywords=get_extraction_api_ids(conn, "datacite"))

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]:
        return get_years(conn, start_year=start_year)

    def count(self, year: int, keywords: list[str]) -> int:
        data = self._get(
            self._url,
            {"query": build_query(year, keywords), "page[size]": 0},
            label=f"({year}, comptage)",
        )
        total = as_mapping(data.get("meta")).get("total")
        return total if isinstance(total, int) else 0

    def fetch_page(self, year: int, keywords: list[str], next_url: str | None) -> DatacitePage:
        if next_url is None:
            data = self._get(
                self._url,
                {
                    "query": build_query(year, keywords),
                    "page[size]": _PAGE_SIZE,
                    "page[cursor]": 1,
                },
                label=f"({year}, première page)",
            )
        else:
            data = self._get(next_url, None, label=f"({year}, page suivante)")
        records = [as_mapping(r) for r in as_sequence(data.get("data"))]
        following = as_str(as_mapping(data.get("links")).get("next"))
        # Une page vide clôt la pagination, même si l'API annonce encore une suite.
        return DatacitePage(records=records, next_url=following if records else None)

    def insert_batch(
        self, conn: Connection, records: list[Mapping[str, JsonValue]]
    ) -> BatchInsertCounts:
        outcomes: list[UpsertOutcome] = []
        for record in records:
            doi = record_doi(record)
            if not doi:
                continue
            inserted, changed = upsert_staging(
                conn, source="datacite", source_id=doi, doi=doi, raw_data=record
            )
            outcomes.append(UpsertOutcome.of(inserted=inserted, changed=changed))
        return BatchInsertCounts(
            new=outcomes.count(UpsertOutcome.NEW),
            updated=outcomes.count(UpsertOutcome.UPDATED),
            unchanged=outcomes.count(UpsertOutcome.UNCHANGED),
        )
