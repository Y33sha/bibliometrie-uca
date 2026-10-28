"""Nouvelle lecture d'un document theses.fr par son identifiant natif : tâche `fetch_stale.theses`.

Lit le détail d'une thèse par son identifiant natif (`staging.source_id` : NNT pour une thèse soutenue, identifiant theses.fr pour une thèse en cours). Le moissonnage écrit seulement les thèses absentes de `staging` : cette tâche met à jour les autres.
"""

from __future__ import annotations

import httpx2

from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.theses.api import fetch_thesis


class ThesesStaleRefetch(StaleRefetch):
    source_key = "theses"
    # theses.fr fragile : une requête à la fois.
    max_concurrent = 1

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        return await fetch_thesis(client, source_id)
