"""Adapter OpenAlex pour `application.pipeline.extract.refresh_stale`.

Refetch d'une row par son id OpenAlex (`staging.source_id`) via `GET /works/{id}`,
qui renvoie le work complet (tous les auteurs). Un 404 = work confirmé absent
(supprimé ou fusionné côté OpenAlex).
"""

from __future__ import annotations

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth
from infrastructure.sources.openalex.parsing import extract_doi
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter


class OpenalexRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "openalex"
    # Plafond OpenAlex 10 req/s (cf. fetch_missing_doi) : 3 workers + 100 ms de pause.
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str

    def configure(self, conn: Connection) -> None:
        init_auth(api_key=get_openalex_api_key(conn), email=get_polite_pool_email(conn))
        self.base_url = get_api_base_urls()["openalex"]

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        try:
            work = await http_request_with_retry_async(
                client,
                "GET",
                f"{self.base_url}/{source_id}",
                params={"select": SELECT_FIELDS, **auth_params()},
                timeout=30,
                label=f"OA {source_id}",
            )
        except httpx.HTTPStatusError as e:
            return NOT_FOUND if e.response.status_code == 404 else None
        except httpx.RequestError:
            return None
        if not isinstance(work, dict) or not work:
            return None
        return FetchedRecord(doi=extract_doi(work), raw_data=work)
