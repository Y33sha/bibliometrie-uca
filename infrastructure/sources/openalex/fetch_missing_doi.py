"""Adapter OpenAlex pour `application.pipeline.cross_imports.fetch_missing_doi`.

Un appel par DOI sur le filtre `doi:...` de l'API Works.

Chemin async (`run_async`). La boucle embarrassingly parallel des DOIs manquants exploite le polite pool OpenAlex (10 req/s) via un sémaphore.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.cross_imports.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.pipeline.extract.cross_import import record_doi_not_found
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import (
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
        init_auth(api_key=get_openalex_api_key(), email=get_polite_pool_email())
        self.base_url = API_BASE_URLS["openalex"]

    async def fetch_async(
        self, client: httpx.AsyncClient, dois: list[str]
    ) -> Iterable[Mapping[str, JsonValue]]:
        doi = dois[0]
        params: dict[str, str | int | float] = {
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
        results = [as_mapping(r) for r in as_sequence(data.get("results"))]
        if not results:
            # Réponse OpenAlex valide, zéro résultat : DOI confirmé absent.
            return [not_found_marker(doi)]
        return results[:1]

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "openalex", as_str(record["_doi"]) or "")
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
