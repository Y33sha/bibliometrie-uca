"""Adapter ScanR pour `application.pipeline.extract.fetch_missing_doi`.

API ElasticSearch — requête `terms` sur `externalIds.id.keyword` pour un
lot de 50 DOI en un seul appel. Authentification basic.

ScanR stocke les DOI en casse variable ; le matching est case-insensitive
côté `get_cross_import_dois` (cf. `infrastructure.sources.common`).

Adapter async (`AsyncFetchMissingDoiAdapter`).
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.common import clean_doi, compute_hash, record_doi_not_found
from infrastructure.sources.config import get_api_base_urls, get_scanr_credentials
from infrastructure.sources.http_retry_async import http_request_with_retry_async

_INSERT_SCANR_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('scanr', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data ELSE staging.raw_data END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE ELSE staging.processed END,
        last_seen_at = now()
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class ScanrFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "scanr"
    batch_size = 50
    # API ElasticSearch publique, pas de rate limit documenté — 5 req
    # concurrentes reste courtois sur une API interne DataESR.
    max_concurrent = 5

    url: str
    auth: tuple[str, str]

    def configure(self, conn: Connection) -> None:
        self.url = get_api_base_urls()["scanr"]
        username, password = get_scanr_credentials(conn)
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
        records = [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]
        # Diff requêtés / trouvés : les DOI du lot sans hit sont confirmés
        # absents de ScanR (réponse ES valide). Comparaison sur DOI nettoyé,
        # cohérente avec les DOI lowercase de `get_cross_import_dois`.
        found = {
            clean_doi(ext.get("id"))
            for rec in records
            for ext in (rec.get("externalIds") or [])
            if ext.get("type") == "doi"
        }
        missed = [not_found_marker(d) for d in dois if d not in found]
        return records + missed

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "scanr", record["_doi"])
            conn.commit()
            return False

        scanr_id = record.get("id", "")
        if not scanr_id:
            return False

        doi = None
        for ext in record.get("externalIds") or []:
            if ext.get("type") == "doi":
                doi = clean_doi(ext.get("id"))
                break

        result = conn.execute(
            _INSERT_SCANR_SQL,
            {
                "source_id": scanr_id,
                "doi": doi,
                "raw_data": record,
                "raw_hash": compute_hash(record),
            },
        )
        conn.commit()
        return result.rowcount > 0
