"""Nouvelle lecture d'un document ScanR par son identifiant natif : tâche `fetch_stale.scanr`.

Une requête Elasticsearch `term` sur `id.keyword` relit le document. Une réponse valide sans résultat confirme l'absence.
"""

from __future__ import annotations

import httpx2

from domain.types import JsonValue
from pipeline.http.lookup import NOT_FOUND, NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.scanr.api import search


class ScanrStaleRefetch(StaleRefetch):
    source_key = "scanr"
    max_concurrent = 5

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        query: dict[str, JsonValue] = {
            "size": 1,
            "query": {"term": {"id.keyword": source_id}},
        }
        records = await search(client, query, label=f"id {source_id}")
        if isinstance(records, NotFound | Unavailable):
            return records
        if not records:
            return NOT_FOUND
        return records[0]
