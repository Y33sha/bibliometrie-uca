"""Nouvelle lecture d'un document Crossref par son identifiant natif : tâche `fetch_stale.crossref`.

CrossRef est native du DOI : son `staging.source_id` **est** le DOI. Le refetch par id natif revient à `GET /works/{doi}`. Un 404 = DOI confirmé absent.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.crossref.api import fetch_work


class CrossrefStaleRefetch(StaleRefetch):
    source_key = "crossref"
    # Polite pool Crossref : 3 requêtes simultanées au plus.
    max_concurrent = 3

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        message = await fetch_work(client, source_id)
        if isinstance(message, NotFound | Unavailable):
            return message
        return message
