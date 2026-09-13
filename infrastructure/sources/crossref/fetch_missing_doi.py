"""Adapter CrossRef pour `application.pipeline.fetch_missing.doi`.

CrossRef est ingérée DOI-driven : pour chaque DOI présent dans une autre source mais absent du staging CrossRef, on interroge l'endpoint `GET /works/{doi}` et on insère le `message` dans `staging` avec `source='crossref'`.

Polite pool obtenu via le header `User-Agent` qui inclut un mailto. Doc CrossRef : polite = 10 req/s + 3 concurrentes. On colle exactement à ces limites (max_concurrent=3, request_delay=0.1 s) pour éviter les 429.

Crossref est la source native du DOI : un 404 est définitif (DOI erroné ou non Crossref). `record_failed_lookup` l'inscrit dans `failed_lookups` sans date de nouvelle tentative. Un DOI alias est redirigé par Crossref vers son DOI principal : le document principal est inséré, et l'alias inscrit de la même façon.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable, Mapping

import httpx2
from sqlalchemy import Connection

from application.ports.pipeline.fetch_missing.doi import (
    is_not_found_marker,
    not_found_marker,
)
from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_str
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.pipeline.fetch_missing.failed_lookups import (
    forget_failed_doi_lookups,
    record_failed_lookup,
)
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_polite_pool_email
from infrastructure.sources.http_retry import http_request_with_retry_async
from infrastructure.sources.polite_pool import build_user_agent


class CrossrefFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "crossref"
    batch_size = 1
    # Polite pool CrossRef : 10 req/s, 3 concurrentes max. Avec sem=3 et ~200 ms de latence par requête, request_delay=0.1 plafonne à 3 / (0.1 + 0.2) ≈ 10 req/s sustained, juste sous la limite.
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["crossref"]
        email = get_polite_pool_email()
        self.headers = {"User-Agent": build_user_agent(email)}

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> Iterable[Mapping[str, JsonValue]]:
        doi = dois[0]
        # CrossRef accepte le DOI tel quel dans le path (slashes inclus, qui font partie d'à peu près 100 % des DOI). On ne quote que les caractères vraiment dangereux.
        url = f"{self.base_url}/works/{urllib.parse.quote(doi, safe='/()')}"
        try:
            data = as_mapping(
                await http_request_with_retry_async(
                    client,
                    "GET",
                    url,
                    headers=self.headers,
                    timeout=30,
                    label=f"DOI {doi}",
                )
            )
        except httpx2.HTTPStatusError as e:
            if e.response.status_code == 404:
                # 404 = DOI confirmé absent de Crossref. insert() l'inscrit dans failed_lookups.
                return [not_found_marker(doi)]
            return []
        except httpx2.RequestError:
            return []

        message = data.get("message")
        if not isinstance(message, dict):
            return []
        if clean_doi(as_str(message.get("DOI"))) != doi:
            # DOI alias, que Crossref redirige vers son DOI principal : le document reçu porte ce dernier. L'alias n'est pas une œuvre de Crossref, source native du DOI : son marqueur l'inscrit définitivement dans failed_lookups.
            return [message, not_found_marker(doi)]
        return [message]

    def insert(
        self, conn: Connection, record: Mapping[str, JsonValue], *, retry_after_days: int
    ) -> bool:
        if is_not_found_marker(record):
            record_failed_lookup(
                conn,
                "crossref",
                "doi",
                as_str(record["_doi"]) or "",
                retry_after_days=retry_after_days,
            )
            return False

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
