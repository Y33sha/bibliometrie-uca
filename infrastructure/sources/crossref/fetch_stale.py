"""Adapter CrossRef pour `application.pipeline.extract.fetch_stale`.

CrossRef est native du DOI : son `staging.source_id` **est** le DOI. Le refetch par id natif revient à `GET /works/{doi}`. Un 404 = DOI confirmé absent.
"""

from __future__ import annotations

import urllib.parse

import httpx2
from sqlalchemy import Connection

from application.ports.pipeline.extract.fetch_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from domain.publications.identifiers import clean_doi
from domain.types import as_mapping, as_str
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_polite_pool_email
from infrastructure.sources.fetch_stale_base import BaseFetchStaleAdapter
from infrastructure.sources.http_retry import http_request_with_retry_async
from infrastructure.sources.polite_pool import build_user_agent


class CrossrefFetchStaleAdapter(BaseFetchStaleAdapter):
    source_key = "crossref"
    # Polite pool CrossRef 10 req/s, 3 concurrentes (cf. fetch_missing_doi).
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["crossref"]
        email = get_polite_pool_email()
        self.headers = {"User-Agent": build_user_agent(email)}

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        url = f"{self.base_url}/works/{urllib.parse.quote(source_id, safe='/()')}"
        try:
            data = as_mapping(
                await http_request_with_retry_async(
                    client,
                    "GET",
                    url,
                    headers=self.headers,
                    timeout=30,
                    label=f"DOI {source_id}",
                )
            )
        except httpx2.HTTPStatusError as e:
            return NOT_FOUND if e.response.status_code == 404 else None
        except httpx2.RequestError:
            return None
        message = data.get("message")
        if not isinstance(message, dict):
            return None
        return FetchedRecord(doi=clean_doi(as_str(message.get("DOI"))), raw_data=message)
