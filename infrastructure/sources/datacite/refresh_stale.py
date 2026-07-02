"""Adapter DataCite pour `application.pipeline.extract.refresh_stale`.

DataCite est native du DOI pour ses préfixes : son `staging.source_id` **est** le
DOI. Le refetch par id natif revient donc à `GET /dois/{doi}` (nœud JSON:API
unique). Un 404 = DOI confirmé absent.
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
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.datacite.fetch_missing_doi import _record_doi
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter

_USER_AGENT_TEMPLATE = "BibliometrieUCA-pipeline/1.0 (mailto:{email})"


class DataciteRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "datacite"
    # Tier identifié DataCite ~3,3 req/s (cf. fetch_missing_doi).
    max_concurrent = 3
    request_delay_s = 0.9

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["datacite"]
        email = get_polite_pool_email(conn)
        self.headers = {
            "User-Agent": _USER_AGENT_TEMPLATE.format(email=email),
            "Accept": "application/vnd.api+json",
        }

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        url = f"{self.base_url}/dois/{urllib.parse.quote(source_id, safe='/()')}"
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
        node = data.get("data")
        if not isinstance(node, dict):
            return None
        return FetchedRecord(doi=_record_doi(node), raw_data=node)
