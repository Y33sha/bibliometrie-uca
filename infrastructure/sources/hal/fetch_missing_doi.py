"""Adapter HAL pour `application.pipeline.cross_imports.fetch_missing_doi`.

HAL fournit une API Solr ; on interroge par DOI (un appel par DOI).

Adapter async (`AsyncFetchMissingDoiAdapter`), parallélisme embarrassingly parallel par DOI via `httpx.AsyncClient`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.cross_imports.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str, at_path
from infrastructure.pipeline.extract.cross_import import record_doi_not_found
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.hal.fields import HAL_FIELDS_STR
from infrastructure.sources.http_retry import http_request_with_retry_async


class HalFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "hal"
    batch_size = 1
    # API Solr publique, pas de rate limit documenté — 5 req concurrentes
    # reste courtois et suffisant pour saturer le pipeline.
    max_concurrent = 5

    base_url: str

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["hal"]

    async def fetch_async(
        self, client: httpx.AsyncClient, dois: list[str]
    ) -> Iterable[Mapping[str, JsonValue]]:
        doi = dois[0]
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.base_url,
                params={
                    "q": f'doiId_s:"{doi}"',
                    "fl": HAL_FIELDS_STR,
                    "wt": "json",
                    "rows": "1",
                },
                timeout=15,
                label=f"DOI {doi}",
            )
        except (httpx.RequestError, httpx.HTTPStatusError):
            return []
        docs = [as_mapping(d) for d in as_sequence(at_path(data, "response").get("docs"))]
        if not docs:
            # Réponse Solr valide, zéro doc : DOI confirmé absent de HAL.
            return [not_found_marker(doi)]
        return docs[:1]

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "hal", as_str(record["_doi"]) or "")
            return False

        hal_id = hal_text_field(record.get("halId_s"))
        if not hal_id:
            return False

        doi = hal_text_field(record.get("doiId_s"))

        inserted, _ = upsert_staging(
            conn,
            source="hal",
            source_id=hal_id,
            doi=doi,
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        return inserted


def hal_text_field(valeur: JsonValue) -> str | None:
    """Champ HAL, qui arrive en texte ou en liste de textes (convention Solr)."""
    if elements := as_sequence(valeur):
        return as_str(elements[0])
    return as_str(valeur)
