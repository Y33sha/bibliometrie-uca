"""Adapter theses.fr pour `application.pipeline.extract.refresh_stale`.

Refetch d'une row par son identifiant natif (`staging.source_id` : NNT pour une
thèse soutenue, id theses.fr pour une thèse en cours). L'interrogation passe par
le **même** endpoint recherche que le bulk, pour un `raw_data` de shape identique,
et retient le hit dont l'`id` correspond exactement. Une réponse valide sans hit
correspondant = identifiant confirmé absent.
"""

from __future__ import annotations

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from infrastructure.sources.api_limits import THESES_DELAY
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter
from infrastructure.sources.theses.extract_theses import extract_doi

# Marge au-dessus d'un hit unique : la recherche libre sur l'identifiant peut
# ramener quelques quasi-homonymes, filtrés ensuite par égalité stricte de l'`id`.
_SEARCH_SIZE = 20


class ThesesRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "theses"
    # theses.fr fragile : un seul worker, cadencé à THESES_DELAY entre appels.
    max_concurrent = 1
    request_delay_s = THESES_DELAY

    url: str

    def configure(self, conn: Connection) -> None:
        self.url = get_api_base_urls()["theses"]

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.url,
                params={"q": source_id, "debut": 0, "nombre": _SEARCH_SIZE},
                timeout=30,
                label=f"these {source_id}",
            )
        except (httpx.RequestError, httpx.HTTPStatusError):
            return None
        for these in data.get("theses", []):
            if these.get("id") == source_id:
                return FetchedRecord(doi=extract_doi(these), raw_data=these)
        return NOT_FOUND
