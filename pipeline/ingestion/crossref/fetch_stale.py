"""Nouvelle lecture d'un document Crossref par son identifiant natif : tâche `fetch_stale.crossref`.

L'identifiant natif d'un document Crossref est son DOI : la nouvelle lecture interroge `GET /works/{doi}`. Un 404 confirme l'absence.
"""

from __future__ import annotations

import httpx2

from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.crossref.api import fetch_work


class CrossrefStaleRefetch(StaleRefetch):
    source_key = "crossref"
    # Polite pool Crossref : 3 requêtes simultanées au plus.
    max_concurrent = 3

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        return await fetch_work(client, source_id)
