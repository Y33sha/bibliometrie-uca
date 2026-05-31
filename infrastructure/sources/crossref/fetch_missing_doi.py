"""Adapter CrossRef pour ``application.pipeline.extract.fetch_missing_doi``.

CrossRef est ingérée DOI-driven : pour chaque DOI présent dans une autre
source mais absent du staging CrossRef, on interroge l'endpoint
``GET /works/{doi}`` et on insère le ``message`` dans ``staging`` avec
``source='crossref'``.

Polite pool obtenu via le header ``User-Agent`` qui inclut un mailto.
Doc CrossRef : polite = 10 req/s + 3 concurrentes. On colle exactement à
ces limites (max_concurrent=3, request_delay=0.1 s) pour éviter les 429.

Les DOI introuvables (HTTP 404) sont stockés avec ``not_found_at`` et
``processed=TRUE`` pour ne pas être réinterrogés à chaque run. Crossref
est la source native du DOI : un 404 est définitif (DOI erroné ou non
Crossref), donc le stub reste dans ``staging`` (pas de backoff).
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
    VALUES ('crossref', :doi, :doi, '{}'::jsonb, now(), TRUE)
    ON CONFLICT (source, source_id) DO NOTHING
    """
)

_INSERT_CROSSREF_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('crossref', :doi, :doi, :raw_data, :raw_hash, FALSE)
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


class CrossrefFetchMissingDoiAdapter:
    """Adapter async conforme au ``AsyncFetchMissingDoiAdapter`` Protocol."""

    source_key = "crossref"
    batch_size = 1
    # Polite pool CrossRef : 10 req/s, 3 concurrentes max. Avec sem=3 et
    # ~200 ms de latence par requête, request_delay=0.1 plafonne à
    # 3 / (0.1 + 0.2) ≈ 10 req/s sustained, juste sous la limite.
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls(conn).get("crossref", "https://api.crossref.org")
        email = get_polite_pool_email(conn)
        self.headers = {"User-Agent": _USER_AGENT_TEMPLATE.format(email=email)}

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        # CrossRef accepte le DOI tel quel dans le path (slashes inclus, qui
        # font partie d'à peu près 100 % des DOI). On ne quote que les
        # caractères vraiment dangereux.
        url = f"{self.base_url}/works/{urllib.parse.quote(doi, safe='/()')}"
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                url,
                headers=self.headers,
                timeout=30,
                label=f"DOI {doi}",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # 404 = DOI confirmé absent de Crossref. Source native du DOI :
                # le miss est définitif, insert() pose un stub `staging`.
                return [not_found_marker(doi)]
            return []
        except httpx.RequestError:
            return []

        message = data.get("message")
        if not isinstance(message, dict):
            return []
        return [message]

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            conn.execute(_INSERT_NOT_FOUND_SQL, {"doi": record["_doi"]})
            conn.commit()
            return False

        # DOI = identifiant CrossRef. On normalise en lowercase pour
        # rester cohérent avec les autres sources qui font de même.
        doi_raw = record.get("DOI", "")
        if not doi_raw:
            return False
        doi = doi_raw.lower()

        result = conn.execute(
            _INSERT_CROSSREF_SQL,
            {"doi": doi, "raw_data": record, "raw_hash": compute_hash(record)},
        )
        conn.commit()
        return result.rowcount > 0
