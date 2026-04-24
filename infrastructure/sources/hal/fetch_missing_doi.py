"""Adapter HAL pour `application.pipeline.fetch_missing_doi`.

HAL fournit une API Solr ; on interroge par DOI (un appel par DOI).
L'insertion gère la colonne `hal_collections` avec merge set-union
sur conflit.

§2.14 : adapter async (`AsyncFetchMissingDoiAdapter`), parallélisme
embarrassingly parallel par DOI via `httpx.AsyncClient`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx
from psycopg.types.json import Jsonb as Json

from infrastructure.api_retry_async import http_request_with_retry_async
from infrastructure.app_config import get_api_base_urls
from infrastructure.hal import HAL_FIELDS_STR
from infrastructure.sources.common import compute_hash


class HalFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "hal"
    batch_size = 1
    # API Solr publique, pas de rate limit documenté — 5 req concurrentes
    # reste courtois et suffisant pour saturer le pipeline.
    max_concurrent = 5

    base_url: str

    def configure(self, cur: Any) -> None:
        self.base_url = get_api_base_urls(cur)["hal"]

    async def fetch_async(
        self, client: httpx.AsyncClient, dois: list[str]
    ) -> Iterable[dict]:
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
        return docs[:1]

    def insert(self, conn: Any, record: dict) -> bool:
        hal_id = record.get("halId_s")
        if isinstance(hal_id, list):
            hal_id = hal_id[0] if hal_id else None
        if not hal_id:
            return False

        doi = record.get("doiId_s")
        if isinstance(doi, list):
            doi = doi[0] if doi else None

        coll_codes = record.get("collCode_s") or []
        hal_collections = (
            coll_codes if isinstance(coll_codes, list) and coll_codes else None
        )
        raw_hash = compute_hash(record)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed, raw_hash)
                VALUES ('hal', %s, %s, %s::jsonb, %s, FALSE, %s)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    raw_data = CASE
                        WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                            THEN EXCLUDED.raw_data
                        ELSE staging.raw_data
                    END,
                    raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
                    hal_collections = CASE
                        WHEN staging.hal_collections IS NULL THEN EXCLUDED.hal_collections
                        WHEN EXCLUDED.hal_collections IS NULL THEN staging.hal_collections
                        ELSE (SELECT array_agg(DISTINCT c) FROM unnest(staging.hal_collections || EXCLUDED.hal_collections) AS c)
                    END,
                    processed = CASE
                        WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                            THEN FALSE
                        ELSE staging.processed
                    END
                """,
                (hal_id, doi, Json(record), hal_collections, raw_hash),
            )
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted
