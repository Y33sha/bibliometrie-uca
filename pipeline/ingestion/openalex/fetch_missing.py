"""Recherche par DOI dans OpenAlex : tâche `fetch_missing.doi.openalex`.

Un appel par DOI sur le filtre `doi:...` de `/works`.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection

from domain.sources.openalex import authors_may_be_truncated
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue, as_mapping, as_sequence
from pipeline.http.http_retry import lookup_json_async
from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.doi_search import DoiBatchResult
from pipeline.ingestion.common.failed_lookups import forget_failed_doi_lookups
from pipeline.ingestion.common.staging import upsert_staging
from pipeline.ingestion.openalex.api import auth_params
from pipeline.ingestion.openalex.fields import SELECT_FIELDS, extract_doi, extract_openalex_id


class OpenalexDoiSearch:
    """Recherche par DOI dans OpenAlex (`DoiSearch`)."""

    source_key = "openalex"
    batch_size = 1
    # OpenAlex plafonne à 10 req/s (polite `mailto` ou authentifié `api_key`, envoyé par `auth_params()`).
    # `max_concurrent=3` × pause 100 ms, latence ~280 ms → ≈ 3 / (0,28 + 0,1) ≈ 7,9 req/s (marge sous le plafond).
    max_concurrent = 3
    request_delay_s = 0.1

    def __init__(self) -> None:
        self.base_url = API_BASE_URLS["openalex"]

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        doi = dois[0]
        params: dict[str, str | int | float] = {
            "filter": f"doi:{doi}",
            "select": SELECT_FIELDS,
            **auth_params(),
        }
        outcome = await lookup_json_async(
            client,
            "GET",
            self.base_url,
            params=params,
            timeout=30,
            not_found_statuses=frozenset(),
            label=f"DOI {doi}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return DoiBatchResult()
        results = [as_mapping(r) for r in as_sequence(as_mapping(outcome).get("results"))]
        if not results:
            # Réponse OpenAlex valide, zéro résultat : DOI confirmé absent.
            return DoiBatchResult(not_found=[doi])
        return DoiBatchResult(records=results[:1])

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        doi = extract_doi(record)
        inserted, _ = upsert_staging(
            conn,
            source="openalex",
            source_id=extract_openalex_id(record),
            doi=doi,
            raw_data=record,
            # La recherche par DOI passe par l'endpoint de liste, plafonné comme le moissonnage.
            authors_truncated=authors_may_be_truncated(record),
            entry_mode=StagingEntryMode.FETCH_MISSING_DOI,
        )
        forget_failed_doi_lookups(conn, "openalex", [doi])
        return inserted
