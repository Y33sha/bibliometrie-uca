"""Adapter ScanR pour `application.pipeline.cross_imports.fetch_missing_doi`.

API ElasticSearch — requête `terms` sur `externalIds.id.keyword` pour un lot de 50 DOI en un seul appel. Authentification basic.

ScanR stocke les DOI en casse variable ; le matching est case-insensitive côté `get_cross_import_dois` (cf. `infrastructure.pipeline.extract.cross_import`).

Adapter async (`AsyncFetchMissingDoiAdapter`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.cross_imports.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.pipeline.extract.cross_import import record_doi_not_found
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_scanr_credentials
from infrastructure.sources.http_retry import http_request_with_retry_async


class ScanrFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "scanr"
    batch_size = 50
    # API ElasticSearch publique, pas de rate limit documenté — 5 req concurrentes reste courtois sur une API interne DataESR.
    max_concurrent = 5

    url: str
    auth: tuple[str, str]

    def configure(self, conn: Connection) -> None:
        self.url = API_BASE_URLS["scanr"]
        username, password = get_scanr_credentials()
        self.auth = (username, password)

    async def fetch_async(
        self, client: httpx.AsyncClient, dois: list[str]
    ) -> Iterable[Mapping[str, JsonValue]]:
        query: dict[str, JsonValue] = {
            "size": len(dois),
            "query": {"terms": {"externalIds.id.keyword": dois}},
        }
        try:
            data = await http_request_with_retry_async(
                client,
                "POST",
                self.url,
                json_body=query,
                auth=self.auth,
                timeout=30,
                label=f"batch {len(dois)} DOI",
            )
        except (httpx.RequestError, httpx.HTTPStatusError):
            # Erreur réseau ou HTTP (401 sur credentials rejetés, 429/5xx après retries, 4xx) : lot ignoré, repris au prochain run (l'absence d'un DOI n'est pas prouvée). Comportement uniforme à toutes les sources.
            return []
        records = [
            as_mapping(as_mapping(hit).get("_source"))
            for hit in as_sequence(as_mapping(data.get("hits")).get("hits"))
        ]
        # Diff requêtés / trouvés : les DOI du lot sans hit sont confirmés absents de ScanR (réponse ES valide). Comparaison sur DOI nettoyé, cohérente avec les DOI lowercase de `get_cross_import_dois`.
        found = {
            clean_doi(as_str(champs.get("id")))
            for rec in records
            for ext in as_sequence(rec.get("externalIds"))
            if as_str((champs := as_mapping(ext)).get("type")) == "doi"
        }
        missed = [not_found_marker(d) for d in dois if d not in found]
        return records + missed

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "scanr", as_str(record["_doi"]) or "")
            return False

        scanr_id = as_str(record.get("id")) or ""
        if not scanr_id:
            return False

        doi = None
        for entree in as_sequence(record.get("externalIds")):
            ext = as_mapping(entree)
            if as_str(ext.get("type")) == "doi":
                doi = clean_doi(as_str(ext.get("id")))
                break

        inserted, _ = upsert_staging(
            conn,
            source="scanr",
            source_id=scanr_id,
            doi=doi,
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        return inserted
