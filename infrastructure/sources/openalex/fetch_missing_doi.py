"""Adapter OpenAlex pour `application.pipeline.fetch_missing_doi`.

Un appel par DOI sur le filtre `doi:...` de l'API Works.

Chemin async (`run_async`). La boucle embarrassingly parallel des
DOIs manquants exploite le polite pool OpenAlex (10 req/s) via un
sémaphore.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_openalex_email,
)
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth
from infrastructure.sources.openalex.parsing import extract_doi, extract_openalex_id

_INSERT_OA_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('openalex', :source_id, :doi, :raw_data, :raw_hash, FALSE)
    ON CONFLICT (source, source_id) DO NOTHING
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class OpenalexFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "openalex"
    batch_size = 1
    # OpenAlex impose 10 req/s comme plafond documenté, quel que soit le pool
    # (polite via `mailto` ou authentifié via `api_key`). `auth_params()` envoie
    # `api_key` si configurée (cas prod), sinon `mailto`.
    # Latence mesurée ~280 ms ; sem=3 donne ~10.8 req/s peak, aligné avec le
    # seuil. Monter à 5 (~18 req/s observé) déclenche des 429 à retardement.
    max_concurrent = 3

    base_url: str

    def configure(self, conn: Connection) -> None:
        init_auth(api_key=get_openalex_api_key(conn), email=get_openalex_email(conn))
        self.base_url = get_api_base_urls(conn)["openalex"]

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

    def insert(self, conn: Connection, record: dict) -> bool:
        result = conn.execute(
            _INSERT_OA_SQL,
            {
                "source_id": extract_openalex_id(record),
                "doi": extract_doi(record),
                "raw_data": record,
                "raw_hash": compute_hash(record),
            },
        )
        conn.commit()
        return result.rowcount > 0
