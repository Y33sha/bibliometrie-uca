"""Adapter OpenAlex pour `application.pipeline.cross_imports.fetch_missing_doi`.

Un appel par DOI sur le filtre `doi:...` de l'API Works.

Chemin async (`run_async`). La boucle embarrassingly parallel des DOIs manquants exploite le polite pool OpenAlex (10 req/s) via un sémaphore.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.cross_imports.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.common import record_doi_not_found, upsert_staging
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)
from infrastructure.sources.http_retry import http_request_with_retry_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth
from infrastructure.sources.openalex.parsing import extract_doi, extract_openalex_id


class OpenalexFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "openalex"
    batch_size = 1
    # OpenAlex plafonne à 10 req/s (polite `mailto` ou authentifié `api_key`, envoyé par `auth_params()`).
    # `max_concurrent=3` × pause 100 ms, latence ~280 ms → ≈ 3 / (0,28 + 0,1) ≈ 7,9 req/s (marge sous le plafond).
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str

    def configure(self, conn: Connection) -> None:
        init_auth(api_key=get_openalex_api_key(conn), email=get_polite_pool_email(conn))
        self.base_url = get_api_base_urls()["openalex"]

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
        except (httpx.RequestError, httpx.HTTPStatusError):
            # Erreur réseau ou HTTP (429/5xx après retries, 4xx) : lot ignoré, les DOI restent candidats au prochain run (leur absence n'est pas prouvée).
            return []
        results = data.get("results", [])
        if not results:
            # Réponse OpenAlex valide, zéro résultat : DOI confirmé absent.
            return [not_found_marker(doi)]
        return results[:1]

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "openalex", record["_doi"])
            return False

        inserted, _ = upsert_staging(
            conn,
            source="openalex",
            source_id=extract_openalex_id(record),
            doi=extract_doi(record),
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        return inserted
