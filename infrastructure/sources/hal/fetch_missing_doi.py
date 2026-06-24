"""Adapter HAL pour `application.pipeline.extract.fetch_missing_doi`.

HAL fournit une API Solr ; on interroge par DOI (un appel par DOI).

Adapter async (`AsyncFetchMissingDoiAdapter`), parallélisme
embarrassingly parallel par DOI via `httpx.AsyncClient`.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.common import record_doi_not_found, upsert_staging
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.hal.fields import HAL_FIELDS_STR
from infrastructure.sources.http_retry_async import http_request_with_retry_async


class HalFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "hal"
    batch_size = 1
    # API Solr publique, pas de rate limit documenté — 5 req concurrentes
    # reste courtois et suffisant pour saturer le pipeline.
    max_concurrent = 5

    base_url: str

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["hal"]

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.base_url,
                params={
                    "q": f'doiId_s:"{doi}"',
                    "fl": HAL_FIELDS_STR,
                    "wt": "json",
                    "rows": "1",
                },
                timeout=15,
                label=f"DOI {doi}",
            )
        except (httpx.RequestError, httpx.HTTPStatusError):
            return []
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            # Réponse Solr valide, zéro doc : DOI confirmé absent de HAL.
            return [not_found_marker(doi)]
        return docs[:1]

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "hal", record["_doi"])
            conn.commit()
            return False

        hal_id = record.get("halId_s")
        if isinstance(hal_id, list):
            hal_id = hal_id[0] if hal_id else None
        if not hal_id:
            return False

        doi = record.get("doiId_s")
        if isinstance(doi, list):
            doi = doi[0] if doi else None

        inserted, _ = upsert_staging(
            conn,
            source="hal",
            source_id=hal_id,
            doi=doi,
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        conn.commit()
        return inserted
