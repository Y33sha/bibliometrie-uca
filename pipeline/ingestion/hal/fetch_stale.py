"""Nouvelle lecture d'un document HAL par son hal-id : tâche `fetch_stale.hal`.

La lecture passe par `find_deposit`. Un doublon absorbé renvoie le dépôt conservé : celui-ci est écrit, et le doublon disparaît. Seule une page de dépôt absente (404) confirme l'absence.
"""

from __future__ import annotations

import httpx2

from pipeline.ingestion.common.stale_refetch import FetchOutcome, StaleRefetch
from pipeline.ingestion.hal.api import find_deposit


class HalStaleRefetch(StaleRefetch):
    source_key = "hal"
    max_concurrent = 5

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        return await find_deposit(client, source_id)
