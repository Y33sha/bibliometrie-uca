"""Recherche par DOI dans OpenAlex : tâche `fetch_missing.doi.openalex`.

Un appel par DOI sur le filtre `doi:...` de `/works`.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.doi_search import DoiBatchResult
from pipeline.ingestion.openalex.api import search_doi


class OpenalexDoiSearch:
    """Recherche par DOI dans OpenAlex (`DoiSearch`)."""

    source_key = "openalex"
    batch_size = 1
    # OpenAlex plafonne à 10 req/s (polite `mailto` ou authentifié `api_key`, envoyé par `auth_params()`).
    # `max_concurrent=3` × pause 100 ms, latence ~280 ms → ≈ 3 / (0,28 + 0,1) ≈ 7,9 req/s (marge sous le plafond).
    max_concurrent = 3
    request_delay_s = 0.1

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        doi = dois[0]
        work = await search_doi(client, doi)
        if isinstance(work, NotFound):
            # Réponse OpenAlex valide, zéro résultat : DOI confirmé absent.
            return DoiBatchResult(not_found=[doi])
        if isinstance(work, Unavailable):
            return DoiBatchResult()
        return DoiBatchResult(records=[work])
