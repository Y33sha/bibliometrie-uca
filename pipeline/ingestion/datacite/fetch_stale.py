"""Nouvelle lecture d'un document DataCite par son identifiant natif : tâche `fetch_stale.datacite`.

DataCite est native du DOI pour ses préfixes : son `staging.source_id` **est** le DOI. Le refetch par id natif revient à `GET /dois/{doi}` (nœud JSON:API unique). Un 404 = DOI confirmé absent.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.datacite.api import fetch_doi


class DataciteStaleRefetch(StaleRefetch):
    source_key = "datacite"
    max_concurrent = 3

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        node = await fetch_doi(client, source_id)
        if isinstance(node, NotFound | Unavailable):
            return node
        return node
