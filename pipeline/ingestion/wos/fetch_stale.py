"""Nouvelle lecture d'un document Web of Science par son identifiant natif : tâche `fetch_stale.wos`.

Refetch d'une row par son UT WoS (`staging.source_id`) via une requête Advanced Search `UT=(<ut>)`. Un lot sans correspondance (HTTP 400) ou une réponse valide sans record = UT confirmé absent.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NOT_FOUND, NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.wos.api import get_records, search


class WosStaleRefetch(StaleRefetch):
    source_key = "wos"
    # API Clarivate rate-limitée (cf. `fetch_missing`) : 2 workers + 500 ms.
    max_concurrent = 2
    request_delay_s = 0.5

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        data = await search(client, f"UT=({source_id})", count=1, label=f"UT {source_id}")
        if isinstance(data, NotFound | Unavailable):
            return data
        records = get_records(data)
        if not records:
            return NOT_FOUND
        return records[0]
