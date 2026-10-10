"""Adapter OpenAlex pour `application.pipeline.fetch_stale.phase`.

Refetch d'une row par son id OpenAlex (`staging.source_id`) via `GET /works/{id}`, qui renvoie le work complet (tous les auteurs). Un 404 = work confirmé absent (supprimé ou fusionné côté OpenAlex).
"""

from __future__ import annotations

import httpx2
from sqlalchemy import Connection

from application.ports.pipeline.fetch_stale import FetchedRecord, FetchOutcome
from application.ports.pipeline.lookup import UNAVAILABLE, NotFound, Unavailable
from domain.types import as_mapping
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.fetch_stale_base import BaseFetchStaleAdapter
from infrastructure.sources.http_retry import lookup_json_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params
from infrastructure.sources.openalex.parsing import extract_doi


class OpenalexFetchStaleAdapter(BaseFetchStaleAdapter):
    source_key = "openalex"
    # Plafond OpenAlex 10 req/s (cf. fetch_missing_doi) : 3 workers + 100 ms de pause.
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["openalex"]

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        outcome = await lookup_json_async(
            client,
            "GET",
            f"{self.base_url}/{source_id}",
            params={"select": SELECT_FIELDS, **auth_params()},
            timeout=30,
            label=f"OA {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        work = as_mapping(outcome)
        if not isinstance(work, dict) or not work:
            return UNAVAILABLE
        return FetchedRecord(doi=extract_doi(work), raw_data=work)
