"""Adapter ScanR pour `application.pipeline.extract.refresh_stale`.

Refetch d'une row par son id ScanR (`staging.source_id`) via une requête
ElasticSearch `term` sur `id.keyword`. Une réponse ES valide sans hit = id
confirmé absent.
"""

from __future__ import annotations

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from infrastructure.sources.common import clean_doi
from infrastructure.sources.config import get_api_base_urls, get_scanr_credentials
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter


class ScanrRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "scanr"
    max_concurrent = 5

    url: str
    auth: tuple[str, str]

    def configure(self, conn: Connection) -> None:
        self.url = get_api_base_urls()["scanr"]
        username, password = get_scanr_credentials(conn)
        self.auth = (username, password)

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        query = {"size": 1, "query": {"term": {"id.keyword": source_id}}}
        try:
            data = await http_request_with_retry_async(
                client,
                "POST",
                self.url,
                json_body=query,
                auth=self.auth,
                timeout=30,
                label=f"id {source_id}",
            )
        except httpx.RequestError:
            return None
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return NOT_FOUND
        record = hits[0]["_source"]
        doi = None
        for ext in record.get("externalIds") or []:
            if ext.get("type") == "doi":
                doi = clean_doi(ext.get("id"))
                break
        return FetchedRecord(doi=doi, raw_data=record)
