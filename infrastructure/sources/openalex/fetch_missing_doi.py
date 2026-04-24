"""Adapter OpenAlex pour `application.pipeline.fetch_missing_doi`.

Un appel par DOI sur le filtre `doi:...` de l'API Works.

§2.14 : migre vers le chemin async (`run_async`). La boucle
embarrassingly parallel des DOIs manquants exploite le polite pool
OpenAlex (10 req/s) via un sémaphore, gain attendu ×8 à ×10 vs la
variante sync.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx
from psycopg.types.json import Jsonb as Json

from infrastructure.api_retry_async import http_request_with_retry_async
from infrastructure.app_config import get_api_base_urls, get_openalex_api_key, get_openalex_email
from infrastructure.sources.common import compute_hash
from infrastructure.sources.openalex import (
    SELECT_FIELDS,
    auth_params,
    extract_doi,
    extract_openalex_id,
    init_auth,
)


class OpenalexFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "openalex"
    batch_size = 1
    # Polite pool OpenAlex = 10 req/s. Latence mesurée ~280 ms
    # (run initial : 9979 DOIs en 555 s avec sem=5 = 18 req/s).
    # sem=3 donne ~10.8 req/s peak, aligné avec le seuil documenté.
    # Monter à 5 déclenche des 429 à retardement (quota rolling du free tier).
    max_concurrent = 3

    base_url: str

    def configure(self, cur: Any) -> None:
        init_auth(api_key=get_openalex_api_key(cur), email=get_openalex_email(cur))
        self.base_url = get_api_base_urls(cur)["openalex"]

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        params = {
            "filter": f"doi:{doi}",
            "select": SELECT_FIELDS,
            **auth_params(),
        }
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.base_url,
                params=params,
                timeout=30,
                label=f"DOI {doi}",
            )
        except httpx.RequestError:
            return []
        return data.get("results", [])[:1]

    def insert(self, conn: Any, record: dict) -> bool:
        oa_id = extract_openalex_id(record)
        doi = extract_doi(record)
        raw_hash = compute_hash(record)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
                VALUES ('openalex', %s, %s, %s::jsonb, %s, FALSE)
                ON CONFLICT (source, source_id) DO NOTHING
                """,
                (oa_id, doi, Json(record), raw_hash),
            )
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted
