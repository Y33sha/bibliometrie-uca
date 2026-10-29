"""Nouvelle lecture d'un document Web of Science par son identifiant natif : tâche `fetch_stale.wos`.

Une requête Advanced Search `UT=(<ut>)` relit le record. Une réponse 400, ou une réponse valide sans record, confirme l'absence.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NOT_FOUND, NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.wos.api import get_records, search


class WosStaleRefetch(StaleRefetch):
    source_key = "wos"
    # API instable : 2 requêtes simultanées au plus.
    max_concurrent = 2

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        data = await search(client, f"UT=({source_id})", count=1, label=f"UT {source_id}")
        if isinstance(data, NotFound | Unavailable):
            return data
        records = get_records(data)
        if not records:
            return NOT_FOUND
        return records[0]
