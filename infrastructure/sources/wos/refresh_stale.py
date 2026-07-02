"""Adapter WoS pour `application.pipeline.extract.refresh_stale`.

Refetch d'une row par son UT WoS (`staging.source_id`) via une requête Advanced
Search `UT=(<ut>)`. Un lot sans correspondance (HTTP 400) ou une réponse valide
sans record = UT confirmé absent.
"""

from __future__ import annotations

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
)
from infrastructure.sources.config import get_api_base_urls, get_wos_api_key
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.refresh_stale_base import BaseRefreshStaleAdapter
from infrastructure.sources.wos.parsing import extract_doi, get_records


class WosRefreshStaleAdapter(BaseRefreshStaleAdapter):
    source_key = "wos"
    # API Clarivate rate-limitée (cf. fetch_missing_doi) : 2 workers + 500 ms.
    max_concurrent = 2
    request_delay_s = 0.5

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["wos"]
        self.headers = {"X-ApiKey": get_wos_api_key(conn), "Accept": "application/json"}

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.base_url,
                headers=self.headers,
                params={
                    "databaseId": "WOS",
                    "usrQuery": f"UT=({source_id})",
                    "count": 1,
                    "firstRecord": 1,
                },
                timeout=60,
                initial_backoff=4.0,
                retry_on_empty_body=True,
                label=f"UT {source_id}",
            )
        except httpx.HTTPStatusError as e:
            # 400 = requête sans correspondance : UT confirmé absent de WoS.
            return NOT_FOUND if e.response.status_code == 400 else None
        except httpx.RequestError:
            return None
        if not data:
            return None
        records = get_records(data)
        if not records:
            return NOT_FOUND
        return FetchedRecord(doi=extract_doi(records[0]), raw_data=records[0])
