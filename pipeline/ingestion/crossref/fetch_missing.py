"""Recherche par DOI dans Crossref : tâche `fetch_missing.doi.crossref`.

CrossRef est ingérée DOI-driven : pour chaque DOI présent dans une autre source mais absent du staging CrossRef, on interroge l'endpoint `GET /works/{doi}` et on insère le `message` dans `staging` avec `source='crossref'`.

Polite pool obtenu via le header `User-Agent` qui inclut un mailto. Doc CrossRef : polite = 10 req/s + 3 concurrentes. On colle exactement à ces limites (max_concurrent=3, request_delay=0.1 s) pour éviter les 429.

Un 404 inscrit le DOI dans `failed_lookups`, et `fetch_missing_doi` le soumet à doi.org. Un DOI alias est redirigé par Crossref vers son DOI principal : le document principal est inséré, et l'alias inscrit comme introuvable.
"""

from __future__ import annotations

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import as_str
from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.common.doi_search import DoiBatchResult
from pipeline.ingestion.crossref.api import fetch_work


class CrossrefDoiSearch:
    """Recherche par DOI dans Crossref (`DoiSearch`) : `GET /works/{doi}`."""

    source_key = "crossref"
    batch_size = 1
    # Polite pool CrossRef : 10 req/s, 3 concurrentes max. Avec sem=3 et ~200 ms de latence par requête, request_delay=0.1 plafonne à 3 / (0.1 + 0.2) ≈ 10 req/s sustained, juste sous la limite.
    max_concurrent = 3
    request_delay_s = 0.1

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        doi = dois[0]
        message = await fetch_work(client, doi)
        if isinstance(message, NotFound):
            # 404 = DOI confirmé absent de Crossref.
            return DoiBatchResult(not_found=[doi])
        if isinstance(message, Unavailable):
            return DoiBatchResult()
        if clean_doi(as_str(message.get("DOI"))) != doi:
            # DOI alias, que Crossref redirige vers son DOI principal : le document reçu a ce dernier pour DOI. L'alias est inscrit comme introuvable.
            return DoiBatchResult(records=[message], not_found=[doi])
        return DoiBatchResult(records=[message])
