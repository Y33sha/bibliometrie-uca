"""Nouvelle lecture d'un document HAL par son hal-id : tâche `fetch_stale.hal`.

Requête Solr `halId_s:<id>`. Une réponse Solr valide sans document confirme l'absence.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.hal.api import search_one


class HalStaleRefetch(StaleRefetch):
    source_key = "hal"
    max_concurrent = 5

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        doc = await search_one(client, f"halId_s:{source_id}", label=f"halId {source_id}")
        if isinstance(doc, NotFound | Unavailable):
            return doc
        return doc
