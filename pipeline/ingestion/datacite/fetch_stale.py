"""Nouvelle lecture d'un document DataCite par son identifiant natif : tâche `fetch_stale.datacite`.

DataCite est native du DOI pour ses préfixes : son `staging.source_id` **est** le DOI. Le refetch par id natif revient à `GET /dois/{doi}` (nœud JSON:API unique). Un 404 = DOI confirmé absent.
"""

from __future__ import annotations

import urllib.parse

import httpx2

from domain.types import as_mapping
from pipeline.http.http_retry import lookup_json_async
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.stale_refetch import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.ingestion.datacite.fields import RECORD_PARAMS, api_headers, record_doi


class DataciteStaleRefetch(StaleRefetch):
    source_key = "datacite"
    # Tier identifié DataCite ~3,3 req/s (cf. `fetch_missing`).
    max_concurrent = 3
    request_delay_s = 0.9

    def __init__(self) -> None:
        self.base_url = API_BASE_URLS["datacite"]
        self.headers = api_headers()

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        url = f"{self.base_url}/dois/{urllib.parse.quote(source_id, safe='/()')}"
        outcome = await lookup_json_async(
            client,
            "GET",
            url,
            params=RECORD_PARAMS,
            headers=self.headers,
            timeout=30,
            label=f"DOI {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        data = as_mapping(outcome)
        node = data.get("data")
        if not isinstance(node, dict):
            return UNAVAILABLE
        return FetchedRecord(doi=record_doi(node), raw_data=node)
