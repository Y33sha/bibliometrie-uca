"""Recherche par DOI dans Crossref : nœud `fetch_missing.doi.crossref`.

CrossRef est ingérée DOI-driven : pour chaque DOI présent dans une autre source mais absent du staging CrossRef, on interroge l'endpoint `GET /works/{doi}` et on insère le `message` dans `staging` avec `source='crossref'`.

Polite pool obtenu via le header `User-Agent` qui inclut un mailto. Doc CrossRef : polite = 10 req/s + 3 concurrentes. On colle exactement à ces limites (max_concurrent=3, request_delay=0.1 s) pour éviter les 429.

Crossref est la source native du DOI : un 404 est définitif (DOI erroné ou non Crossref). `record_failed_lookup` l'inscrit dans `failed_lookups` sans date de nouvelle tentative. Un DOI alias est redirigé par Crossref vers son DOI principal : le document principal est inséré, et l'alias inscrit de la même façon.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_str
from pipeline.config import get_polite_pool_email
from pipeline.ingestion.failed_lookups import forget_failed_doi_lookups
from pipeline.ingestion.fetch_missing import DoiBatchResult
from pipeline.ingestion.http.api_params import API_BASE_URLS
from pipeline.ingestion.http.http_retry import lookup_json_async
from pipeline.ingestion.http.lookup import NotFound, Unavailable
from pipeline.ingestion.http.polite_pool import build_user_agent
from pipeline.ingestion.staging import upsert_staging


class CrossrefDoiSearch:
    """Recherche par DOI dans Crossref (`DoiSearch`) : `GET /works/{doi}`."""

    source_key = "crossref"
    batch_size = 1
    # Polite pool CrossRef : 10 req/s, 3 concurrentes max. Avec sem=3 et ~200 ms de latence par requête, request_delay=0.1 plafonne à 3 / (0.1 + 0.2) ≈ 10 req/s sustained, juste sous la limite.
    max_concurrent = 3
    request_delay_s = 0.1

    def __init__(self) -> None:
        self.base_url = API_BASE_URLS["crossref"]
        self.headers = {"User-Agent": build_user_agent(get_polite_pool_email())}

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        doi = dois[0]
        # CrossRef accepte le DOI tel quel dans le path (slashes inclus, qui font partie d'à peu près 100 % des DOI). On ne quote que les caractères vraiment dangereux.
        url = f"{self.base_url}/works/{urllib.parse.quote(doi, safe='/()')}"
        outcome = await lookup_json_async(
            client, "GET", url, headers=self.headers, timeout=30, label=f"DOI {doi}"
        )
        if isinstance(outcome, NotFound):
            # 404 = DOI confirmé absent de Crossref.
            return DoiBatchResult(not_found=[doi])
        if isinstance(outcome, Unavailable):
            return DoiBatchResult()
        message = as_mapping(outcome).get("message")
        if not isinstance(message, dict):
            return DoiBatchResult()
        if clean_doi(as_str(message.get("DOI"))) != doi:
            # DOI alias, que Crossref redirige vers son DOI principal : le document reçu porte ce dernier. L'alias n'est pas une œuvre de Crossref, source native du DOI : il est inscrit définitivement dans failed_lookups.
            return DoiBatchResult(records=[as_mapping(message)], not_found=[doi])
        return DoiBatchResult(records=[as_mapping(message)])

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        # DOI = identifiant CrossRef. On le passe par `clean_doi` (normalisation canonique partagée : lowercase, strip URL/ponctuation/suffixes) pour rester cohérent avec les autres sources et la colonne `doi`.
        doi = clean_doi(as_str(record.get("DOI")))
        if not doi:
            return False
        inserted, _ = upsert_staging(
            conn,
            source="crossref",
            source_id=doi,
            doi=doi,
            raw_data=record,
            entry_mode="fetch_missing_doi",
        )
        forget_failed_doi_lookups(conn, "crossref", [doi])
        return inserted
