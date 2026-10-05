"""Adapter DataCite pour `application.pipeline.extract.fetch_stale`.

DataCite est native du DOI pour ses préfixes : son `staging.source_id` **est** le DOI. Le refetch par id natif revient à `GET /dois/{doi}` (nœud JSON:API unique). Un 404 = DOI confirmé absent.
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
from domain.types import as_mapping
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.datacite.nodes import api_headers, record_doi
from infrastructure.sources.fetch_stale_base import BaseFetchStaleAdapter
from infrastructure.sources.http_retry import http_request_with_retry_async


class DataciteFetchStaleAdapter(BaseFetchStaleAdapter):
    source_key = "datacite"
    # Tier identifié DataCite ~3,3 req/s (cf. fetch_missing_doi).
    max_concurrent = 3
    request_delay_s = 0.9

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["datacite"]
        self.headers = api_headers()

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        url = f"{self.base_url}/dois/{urllib.parse.quote(source_id, safe='/()')}"
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
        node = data.get("data")
        if not isinstance(node, dict):
            return None
        return FetchedRecord(doi=record_doi(node), raw_data=node)
