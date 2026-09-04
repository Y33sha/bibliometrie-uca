"""Adapter ScanR pour `application.pipeline.extract.refresh_stale`.

Refetch d'une row par son id ScanR (`staging.source_id`) via une requête ElasticSearch `term` sur `id.keyword`. Une réponse ES valide sans hit = id confirmé absent.
"""

from __future__ import annotations

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_scanr_credentials
from infrastructure.sources.http_retry import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter


class ScanrRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "scanr"
    max_concurrent = 5

    url: str
    auth: tuple[str, str]

    def configure(self, conn: Connection) -> None:
        self.url = API_BASE_URLS["scanr"]
        username, password = get_scanr_credentials()
        self.auth = (username, password)

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        query: dict[str, JsonValue] = {
            "size": 1,
            "query": {"term": {"id.keyword": source_id}},
        }
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
        hits = as_sequence(as_mapping(data.get("hits")).get("hits"))
        if not hits:
            return NOT_FOUND
        record = as_mapping(as_mapping(hits[0]).get("_source"))
        doi = None
        for entree in as_sequence(record.get("externalIds")):
            ext = as_mapping(entree)
            if as_str(ext.get("type")) == "doi":
                doi = clean_doi(as_str(ext.get("id")))
                break
        return FetchedRecord(doi=doi, raw_data=record)
