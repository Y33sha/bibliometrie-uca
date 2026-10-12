"""Nouvelle lecture d'un document Crossref par son identifiant natif : nœud `fetch_stale.crossref`.

CrossRef est native du DOI : son `staging.source_id` **est** le DOI. Le refetch par id natif revient à `GET /works/{doi}`. Un 404 = DOI confirmé absent.
"""

from __future__ import annotations

import urllib.parse

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import as_mapping, as_str
from pipeline.config import get_polite_pool_email
from pipeline.ingestion.fetch_stale import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.ingestion.http.api_params import API_BASE_URLS
from pipeline.ingestion.http.http_retry import lookup_json_async
from pipeline.ingestion.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.http.polite_pool import build_user_agent


class CrossrefStaleRefetch(StaleRefetch):
    source_key = "crossref"
    # Polite pool CrossRef 10 req/s, 3 concurrentes (cf. `fetch_missing`).
    max_concurrent = 3
    request_delay_s = 0.1

    def __init__(self) -> None:
        self.base_url = API_BASE_URLS["crossref"]
        self.headers = {"User-Agent": build_user_agent(get_polite_pool_email())}

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        url = f"{self.base_url}/works/{urllib.parse.quote(source_id, safe='/()')}"
        outcome = await lookup_json_async(
            client,
            "GET",
            url,
            headers=self.headers,
            timeout=30,
            label=f"DOI {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        data = as_mapping(outcome)
        message = data.get("message")
        if not isinstance(message, dict):
            return UNAVAILABLE
        return FetchedRecord(doi=clean_doi(as_str(message.get("DOI"))), raw_data=message)
