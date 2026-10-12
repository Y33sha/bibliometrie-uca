"""Nouvelle lecture d'un document HAL par son hal-id : nœud `fetch_stale.hal`.

Requête Solr `halId_s:<id>`. Absence confirmée = réponse Solr valide, zéro document.
"""

from __future__ import annotations

import httpx2

from pipeline.ingestion.fetch_stale import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.ingestion.hal.fetch_missing import search_one
from pipeline.ingestion.hal.fields import extract_doi
from pipeline.ingestion.http.lookup import NotFound, Unavailable


class HalStaleRefetch(StaleRefetch):
    source_key = "hal"
    max_concurrent = 5

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        doc = await search_one(client, f"halId_s:{source_id}", label=f"halId {source_id}")
        if isinstance(doc, NotFound | Unavailable):
            return doc
        return FetchedRecord(doi=extract_doi(doc), raw_data=doc)
