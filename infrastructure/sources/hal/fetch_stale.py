"""Adapter HAL pour `application.pipeline.fetch_stale.phase`.

Refetch d'une row par son hal-id (`staging.source_id`) via une requête Solr `halId_s:<id>`. Absence confirmée = réponse Solr valide, zéro doc.
"""

from __future__ import annotations

import httpx2
from sqlalchemy import Connection

from application.ports.pipeline.fetch_stale import FetchedRecord, FetchOutcome
from application.ports.pipeline.lookup import NOT_FOUND, NotFound, Unavailable
from domain.types import as_mapping, as_sequence, at_path
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.fetch_stale_base import BaseFetchStaleAdapter
from infrastructure.sources.hal.extract_hal import extract_doi
from infrastructure.sources.hal.fields import HAL_FIELDS_STR
from infrastructure.sources.http_retry import lookup_json_async


class HalFetchStaleAdapter(BaseFetchStaleAdapter):
    source_key = "hal"
    max_concurrent = 5

    base_url: str

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["hal"]

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        outcome = await lookup_json_async(
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
            not_found_statuses=frozenset(),
            label=f"halId {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        data = as_mapping(outcome)
        docs = [as_mapping(d) for d in as_sequence(at_path(data, "response").get("docs"))]
        if not docs:
            return NOT_FOUND
        return FetchedRecord(doi=extract_doi(docs[0]), raw_data=docs[0])
