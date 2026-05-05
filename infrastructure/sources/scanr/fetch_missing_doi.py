"""Adapter ScanR pour `application.pipeline.fetch_missing_doi`.

API ElasticSearch — requête `terms` sur `externalIds.id.keyword` pour un
lot de 50 DOI en un seul appel. Authentification basic.

ScanR stocke les DOI en casse variable ; le matching est case-insensitive
côté `get_cross_import_dois` (cf. `infrastructure.sources.common`).

Adapter async (`AsyncFetchMissingDoiAdapter`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx
from psycopg.types.json import Jsonb as Json

from infrastructure.api_retry_async import http_request_with_retry_async
from infrastructure.app_config import get_api_base_urls, get_scanr_credentials
from infrastructure.sources.common import clean_doi, compute_hash


class ScanrFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "scanr"
    batch_size = 50
    # API ElasticSearch publique, pas de rate limit documenté — 5 req
    # concurrentes reste courtois sur une API interne DataESR.
    max_concurrent = 5

    url: str
    auth: tuple[str, str]

    def configure(self, cur: Any) -> None:
        self.url = get_api_base_urls(cur).get(
            "scanr",
            "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
        )
        username, password = get_scanr_credentials(cur)
        self.auth = (username, password)

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        query = {"size": len(dois), "query": {"terms": {"externalIds.id.keyword": dois}}}
        try:
            data = await http_request_with_retry_async(
                client,
                "POST",
                self.url,
                json_body=query,
                auth=self.auth,
                timeout=30,
                label=f"batch {len(dois)} DOI",
            )
        except (httpx.RequestError, httpx.HTTPStatusError):
            return []
        return [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]

    def insert(self, conn: Any, record: dict) -> bool:
        scanr_id = record.get("id", "")
        if not scanr_id:
            return False

        doi = None
        for ext in record.get("externalIds") or []:
            if ext.get("type") == "doi":
                doi = clean_doi(ext.get("id"))
                break

        raw_hash = compute_hash(record)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
                VALUES ('scanr', %s, %s, %s, %s)
                ON CONFLICT (source, source_id) DO NOTHING
                """,
                (scanr_id, doi, Json(record), raw_hash),
            )
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted
