"""Nouvelle lecture d'un document ScanR par son identifiant natif : nœud `fetch_stale.scanr`.

Refetch d'une row par son id ScanR (`staging.source_id`) via une requête ElasticSearch `term` sur `id.keyword`. Une réponse ES valide sans hit = id confirmé absent.
"""

from __future__ import annotations

import httpx2

from domain.types import JsonValue, as_mapping, as_sequence
from pipeline.http.http_retry import lookup_json_async
from pipeline.http.lookup import NOT_FOUND, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.fetch_stale import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.ingestion.scanr.fields import extract_doi
from pipeline.runtime.config import get_scanr_credentials


class ScanrStaleRefetch(StaleRefetch):
    source_key = "scanr"
    max_concurrent = 5

    def __init__(self) -> None:
        self.url = API_BASE_URLS["scanr"]
        self.auth = get_scanr_credentials()

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        query: dict[str, JsonValue] = {
            "size": 1,
            "query": {"term": {"id.keyword": source_id}},
        }
        outcome = await lookup_json_async(
            client,
            "POST",
            self.url,
            json_body=query,
            auth=self.auth,
            timeout=30,
            not_found_statuses=frozenset(),
            label=f"id {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        data = as_mapping(outcome)
        hits = as_sequence(as_mapping(data.get("hits")).get("hits"))
        if not hits:
            return NOT_FOUND
        record = as_mapping(as_mapping(hits[0]).get("_source"))
        return FetchedRecord(doi=extract_doi(record), raw_data=record)
