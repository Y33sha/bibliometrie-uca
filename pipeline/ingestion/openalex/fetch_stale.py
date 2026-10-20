"""Nouvelle lecture d'un work OpenAlex par son identifiant : tâche `fetch_stale.openalex`.

`GET /works/{id}` rend le work complet, avec tous ses auteurs. Un 404 = work confirmé absent (supprimé ou fusionné dans OpenAlex).
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.fetch_stale import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.ingestion.openalex.api import fetch_work
from pipeline.ingestion.openalex.fields import extract_doi


class OpenalexStaleRefetch(StaleRefetch):
    source_key = "openalex"
    # Plafond OpenAlex 10 req/s : 3 workers et 100 ms de pause.
    max_concurrent = 3
    request_delay_s = 0.1

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        work = await fetch_work(client, source_id)
        if isinstance(work, NotFound | Unavailable):
            return work
        return FetchedRecord(doi=extract_doi(work), raw_data=work)
