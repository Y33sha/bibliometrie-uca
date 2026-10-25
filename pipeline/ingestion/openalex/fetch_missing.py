"""Recherche par DOI dans OpenAlex : tâche `fetch_missing.doi.openalex`.

Un appel par DOI sur le filtre `doi:...` de `/works`.
"""

from __future__ import annotations

import httpx2

from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.common.lookup import LookupBatch
from pipeline.ingestion.openalex.api import search_doi


class OpenalexDoiSearch:
    """Recherche par DOI dans OpenAlex (`DoiSearch`)."""

    source_key = "openalex"
    batch_size = 1
    max_concurrent = 3

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        doi = dois[0]
        work = await search_doi(client, doi)
        if isinstance(work, NotFound):
            # Réponse OpenAlex valide, zéro résultat : DOI confirmé absent.
            return LookupBatch(absent=[doi])
        if isinstance(work, Unavailable):
            return UNAVAILABLE
        return LookupBatch(records=[work])
