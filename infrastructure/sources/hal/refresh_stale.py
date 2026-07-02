"""Adapter HAL pour `application.pipeline.extract.refresh_stale`.

Refetch d'une row par son hal-id (`staging.source_id`) via une requête Solr
`halId_s:<id>`. Absence confirmée = réponse Solr valide, zéro doc.
"""

from __future__ import annotations

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.hal.extract_hal import extract_doi
from infrastructure.sources.hal.fields import HAL_FIELDS_STR
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter


class HalRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "hal"
    max_concurrent = 5

    base_url: str

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["hal"]

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.base_url,
                params={
                    "q": f"halId_s:{source_id}",
                    "fl": HAL_FIELDS_STR,
                    "wt": "json",
                    "rows": "1",
                },
                timeout=15,
                label=f"halId {source_id}",
            )
        except (httpx.RequestError, httpx.HTTPStatusError):
            return None
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return NOT_FOUND
        return FetchedRecord(doi=extract_doi(docs[0]), raw_data=docs[0])
