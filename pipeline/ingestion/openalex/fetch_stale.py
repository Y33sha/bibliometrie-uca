"""Nouvelle lecture d'un work OpenAlex par son identifiant : tâche `fetch_stale.openalex`.

`GET /works/{id}` renvoie le work complet, avec tous ses auteurs. Un 404 confirme l'absence : work supprimé ou fusionné dans OpenAlex.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.openalex.api import fetch_work


class OpenalexStaleRefetch(StaleRefetch):
    source_key = "openalex"
    max_concurrent = 3

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        work = await fetch_work(client, source_id)
        if isinstance(work, NotFound | Unavailable):
            return work
        return work
