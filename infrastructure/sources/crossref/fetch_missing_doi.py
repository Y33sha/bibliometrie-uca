"""Adapter CrossRef pour ``application.pipeline.fetch_missing_doi``.

CrossRef est ingérée DOI-driven : pour chaque DOI présent dans une autre
source mais absent du staging CrossRef, on interroge l'endpoint
``GET /works/{doi}`` et on insère le ``message`` dans ``staging`` avec
``source='crossref'``.

Polite pool obtenu via le header ``User-Agent`` qui inclut un mailto.
Doc CrossRef : polite = 10 req/s + 3 concurrentes. On colle exactement à
ces limites (max_concurrent=3, request_delay=0.1 s) pour éviter les 429.

Les DOI introuvables (HTTP 404) sont stockés avec ``not_found=TRUE`` et
``processed=TRUE`` pour ne pas être réinterrogés à chaque run.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from typing import Any

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.api_retry_async import http_request_with_retry_async
from infrastructure.app_config import get_api_base_urls, get_crossref_email
from infrastructure.sources.common import compute_hash

_USER_AGENT_TEMPLATE = "BibliometrieUCA-pipeline/1.0 (mailto:{email})"

_INSERT_NOT_FOUND_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, not_found, processed)
    VALUES ('crossref', :doi, :doi, '{}'::jsonb, TRUE, TRUE)
    ON CONFLICT (source, source_id) DO NOTHING
    """
)

_INSERT_CROSSREF_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('crossref', :doi, :doi, :raw_data, :raw_hash, FALSE)
    ON CONFLICT (source, source_id) DO NOTHING
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

    def configure(self, conn: Any) -> None:
        self.base_url = get_api_base_urls(conn).get("crossref", "https://api.crossref.org")
        email = get_crossref_email(conn)
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
                # Sentinelle : insert() insérera un stub not_found=TRUE.
                return [{"_status": "not_found", "DOI": doi}]
            return []
        except httpx.RequestError:
            return []

        message = data.get("message")
        if not isinstance(message, dict):
            return []
        return [message]

    def insert(self, conn: Any, record: dict) -> bool:
        # DOI = identifiant CrossRef. On normalise en lowercase pour
        # rester cohérent avec les autres sources qui font de même.
        doi_raw = record.get("DOI", "")
        if not doi_raw:
            return False
        doi = doi_raw.lower()

        if record.get("_status") == "not_found":
            result = conn.execute(_INSERT_NOT_FOUND_SQL, {"doi": doi})
            conn.commit()
            return result.rowcount > 0

        result = conn.execute(
            _INSERT_CROSSREF_SQL,
            {"doi": doi, "raw_data": record, "raw_hash": compute_hash(record)},
        )
        conn.commit()
        return result.rowcount > 0
