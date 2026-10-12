"""Nouvelle lecture d'un document Web of Science par son identifiant natif : nœud `fetch_stale.wos`.

Refetch d'une row par son UT WoS (`staging.source_id`) via une requête Advanced Search `UT=(<ut>)`. Un lot sans correspondance (HTTP 400) ou une réponse valide sans record = UT confirmé absent.
"""

from __future__ import annotations

import httpx2

from domain.types import as_mapping
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_wos_api_key
from infrastructure.sources.http_retry import lookup_json_async
from infrastructure.sources.lookup import NOT_FOUND, UNAVAILABLE, NotFound, Unavailable
from pipeline.sources.fetch_stale import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.sources.wos.fields import extract_doi, get_records


class WosStaleRefetch(StaleRefetch):
    source_key = "wos"
    # API Clarivate rate-limitée (cf. `fetch_missing`) : 2 workers + 500 ms.
    max_concurrent = 2
    request_delay_s = 0.5

    def __init__(self) -> None:
        self.base_url = API_BASE_URLS["wos"]
        self.headers = {"X-ApiKey": get_wos_api_key(), "Accept": "application/json"}

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        outcome = await lookup_json_async(
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
            # 400 = requête sans correspondance : UT confirmé absent de WoS.
            not_found_statuses=frozenset({400}),
            label=f"UT {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        data = as_mapping(outcome)
        if not data:
            return UNAVAILABLE
        records = get_records(data)
        if not records:
            return NOT_FOUND
        return FetchedRecord(doi=extract_doi(records[0]), raw_data=records[0])
