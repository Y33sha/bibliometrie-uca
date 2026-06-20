"""Adapter DataCite pour ``application.pipeline.extract.fetch_missing_doi``.

DataCite est ingérée DOI-driven, sur le même mode que CrossRef : pour chaque
DOI présent dans une autre source mais absent du staging DataCite, on interroge
l'endpoint ``GET /dois/{doi}`` (réponse JSON:API) et on insère le nœud
``data`` (id + ``attributes`` + ``relationships``) dans ``staging`` avec
``source='datacite'``.

Le pool de DOI candidats est filtré en amont par ``get_cross_import_dois`` :
seuls les DOI dont le préfixe résout à la RA ``DataCite`` (ou pas encore résolu)
sont soumis, ce qui évite les 404 systématiques sur les DOI Crossref.

Les DOI introuvables (HTTP 404) sont stockés avec ``not_found_at`` et
``processed=TRUE`` pour ne pas être réinterrogés à chaque run. DataCite est la
source native du DOI pour ses préfixes : un 404 est définitif (DOI erroné ou
non DataCite), donc le stub reste dans ``staging`` (pas de backoff).
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.http_retry_async import http_request_with_retry_async

_USER_AGENT_TEMPLATE = "BibliometrieUCA-pipeline/1.0 (mailto:{email})"

_INSERT_NOT_FOUND_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, not_found_at, processed)
    VALUES ('datacite', :doi, :doi, '{}'::jsonb, now(), TRUE)
    ON CONFLICT (source, source_id) DO NOTHING
    """
)

_INSERT_DATACITE_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('datacite', :doi, :doi, :raw_data, :raw_hash, FALSE)
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


class DataciteFetchMissingDoiAdapter:
    """Adapter async conforme au ``AsyncFetchMissingDoiAdapter`` Protocol."""

    source_key = "datacite"
    batch_size = 1
    # DataCite throttle agressivement les clients non authentifiés : ~10 req/s
    # (3 concurrentes) déclenche des 429 en rafale. On interroge en série avec
    # une pause franche (~1,3 req/s sustained) pour ne pas se faire limiter.
    max_concurrent = 1
    request_delay_s = 0.5

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls(conn).get("datacite", "https://api.datacite.org")
        email = get_polite_pool_email(conn)
        self.headers = {
            "User-Agent": _USER_AGENT_TEMPLATE.format(email=email),
            "Accept": "application/vnd.api+json",
        }

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        url = f"{self.base_url}/dois/{urllib.parse.quote(doi, safe='')}"
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                url,
                headers=self.headers,
                timeout=30,
                max_retries=5,
                initial_backoff=2.0,
                label=f"DOI {doi}",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # 404 = DOI confirmé absent de DataCite. Source native du DOI
                # pour ses préfixes : le miss est définitif, insert() pose un
                # stub `staging`.
                return [not_found_marker(doi)]
            return []
        except httpx.RequestError:
            return []

        record = data.get("data")
        if not isinstance(record, dict):
            return []
        return [record]

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            conn.execute(_INSERT_NOT_FOUND_SQL, {"doi": record["_doi"]})
            conn.commit()
            return False

        # `record` est le nœud JSON:API `data` : son `id` est le DOI, dupliqué
        # dans `attributes.doi`. On normalise en lowercase comme les autres
        # sources.
        attributes = record.get("attributes")
        doi_raw = ""
        if isinstance(attributes, dict):
            doi_raw = attributes.get("doi") or ""
        doi_raw = doi_raw or record.get("id") or ""
        if not doi_raw:
            return False
        doi = doi_raw.lower()

        result = conn.execute(
            _INSERT_DATACITE_SQL,
            {"doi": doi, "raw_data": record, "raw_hash": compute_hash(record)},
        )
        conn.commit()
        return result.rowcount > 0
