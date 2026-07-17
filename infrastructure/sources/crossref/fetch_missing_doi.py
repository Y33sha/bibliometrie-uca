"""Adapter CrossRef pour `application.pipeline.cross_imports.fetch_missing_doi`.

CrossRef est ingérée DOI-driven : pour chaque DOI présent dans une autre
source mais absent du staging CrossRef, on interroge l'endpoint
`GET /works/{doi}` et on insère le `message` dans `staging` avec
`source='crossref'`.

Polite pool obtenu via le header `User-Agent` qui inclut un mailto.
Doc CrossRef : polite = 10 req/s + 3 concurrentes. On colle exactement à
ces limites (max_concurrent=3, request_delay=0.1 s) pour éviter les 429.

Crossref est la source native du DOI : un 404 est définitif (DOI erroné ou non
Crossref). Le miss est mémorisé dans `doi_lookups` avec `next_retry = NULL`
(jamais retenté), ce qui l'exclut définitivement du pool de cross-import.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.cross_imports.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from domain.publications.identifiers import clean_doi
from infrastructure.sources.common import record_doi_not_found, upsert_staging
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.http_retry_async import http_request_with_retry_async

_USER_AGENT_TEMPLATE = "BibliometrieUCA-pipeline/1.0 (mailto:{email})"


class CrossrefFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "crossref"
    batch_size = 1
    # Polite pool CrossRef : 10 req/s, 3 concurrentes max. Avec sem=3 et
    # ~200 ms de latence par requête, request_delay=0.1 plafonne à
    # 3 / (0.1 + 0.2) ≈ 10 req/s sustained, juste sous la limite.
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["crossref"]
        email = get_polite_pool_email(conn)
        self.headers = {"User-Agent": _USER_AGENT_TEMPLATE.format(email=email)}

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        # CrossRef accepte le DOI tel quel dans le path (slashes inclus, qui
        # font partie d'à peu près 100 % des DOI). On ne quote que les
        # caractères vraiment dangereux.
        url = f"{self.base_url}/works/{urllib.parse.quote(doi, safe='/()')}"
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                url,
                headers=self.headers,
                timeout=30,
                label=f"DOI {doi}",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # 404 = DOI confirmé absent de Crossref (source native du DOI, miss
                # définitif). insert() le mémorise dans doi_lookups (permanent).
                return [not_found_marker(doi)]
            return []
        except httpx.RequestError:
            return []

        message = data.get("message")
        if not isinstance(message, dict):
            return []
        return [message]

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            # Source native du DOI : un 404 est définitif → doi_lookups permanent, jamais retenté.
            record_doi_not_found(conn, "crossref", record["_doi"], permanent=True)
            return False

        # DOI = identifiant CrossRef. On le passe par `clean_doi` (normalisation
        # canonique partagée : lowercase, strip URL/ponctuation/suffixes) pour
        # rester cohérent avec les autres sources et la colonne `doi`.
        doi = clean_doi(record.get("DOI"))
        if not doi:
            return False
        inserted, _ = upsert_staging(
            conn,
            source="crossref",
            source_id=doi,
            doi=doi,
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        return inserted
