"""Recherche par DOI dans Crossref : tâche `fetch_missing.doi.crossref`.

Chaque DOI vu dans une autre source et absent de Crossref s'interroge par `GET /works/{doi}` ; le `message` reçu s'écrit dans `staging`. Le polite pool de Crossref admet 10 requêtes par seconde, dont 3 simultanées.

Un 404 inscrit le DOI dans `failed_lookups`, et `fetch_missing_doi` le soumet à doi.org. Crossref redirige un DOI alias vers son DOI principal : le document principal s'écrit, et l'alias est inscrit comme introuvable.
"""

from __future__ import annotations

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import as_str
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.common.lookup import LookupBatch
from pipeline.ingestion.crossref.api import fetch_work


class CrossrefDoiSearch:
    """Recherche par DOI dans Crossref (`DoiSearch`) : `GET /works/{doi}`."""

    source_key = "crossref"
    batch_size = 1
    # Polite pool Crossref : 3 requêtes simultanées au plus.
    max_concurrent = 3

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        doi = dois[0]
        message = await fetch_work(client, doi)
        if isinstance(message, NotFound):
            # 404 : DOI absent de Crossref.
            return LookupBatch(absent=[doi])
        if isinstance(message, Unavailable):
            return UNAVAILABLE
        if clean_doi(as_str(message.get("DOI"))) != doi:
            # DOI alias, redirigé vers le DOI principal du document reçu.
            return LookupBatch(records=[message], absent=[doi])
        return LookupBatch(records=[message])
