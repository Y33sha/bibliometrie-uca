"""Nouvelle lecture d'un document theses.fr par son identifiant natif : tâche `fetch_stale.theses`.

Refetch d'une row par son identifiant natif (`staging.source_id` : NNT pour une thèse soutenue, id theses.fr pour une thèse en cours). Une réponse valide sans hit correspondant = identifiant confirmé absent.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.api_params import THESES_DELAY
from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.theses.api import fetch_thesis


class ThesesStaleRefetch(StaleRefetch):
    source_key = "theses"
    # theses.fr fragile : un seul worker, cadencé à THESES_DELAY entre appels.
    max_concurrent = 1
    request_delay_s = THESES_DELAY

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        thesis = await fetch_thesis(client, source_id)
        if isinstance(thesis, NotFound | Unavailable):
            return thesis
        return thesis
