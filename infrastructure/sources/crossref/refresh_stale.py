"""Adapter CrossRef pour `application.pipeline.extract.refresh_stale`.

CrossRef est native du DOI : son `staging.source_id` **est** le DOI. Le refetch
par id natif revient donc à `GET /works/{doi}`. Un 404 = DOI confirmé absent.
"""

from __future__ import annotations

import urllib.parse

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from domain.publications.identifiers import clean_doi
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter

_USER_AGENT_TEMPLATE = "BibliometrieUCA-pipeline/1.0 (mailto:{email})"


class CrossrefRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "crossref"
    # Polite pool CrossRef 10 req/s, 3 concurrentes (cf. fetch_missing_doi).
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["crossref"]
        email = get_polite_pool_email(conn)
        self.headers = {"User-Agent": _USER_AGENT_TEMPLATE.format(email=email)}

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        url = f"{self.base_url}/works/{urllib.parse.quote(source_id, safe='/()')}"
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                url,
                headers=self.headers,
                timeout=30,
                label=f"DOI {source_id}",
            )
        except httpx.HTTPStatusError as e:
            return NOT_FOUND if e.response.status_code == 404 else None
        except httpx.RequestError:
            return None
        message = data.get("message")
        if not isinstance(message, dict):
            return None
        return FetchedRecord(doi=clean_doi(message.get("DOI")), raw_data=message)
