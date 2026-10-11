"""Adapter HAL pour `application.pipeline.fetch_missing.doi`.

HAL fournit une API Solr ; on interroge par DOI (un appel par DOI).

Adapter async (`AsyncFetchMissingDoiAdapter`), parallélisme embarrassingly parallel par DOI via `httpx2.AsyncClient`.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection

from application.ports.pipeline.fetch_missing.doi import DoiBatchResult
from application.ports.pipeline.lookup import NotFound, Unavailable
from domain.types import JsonValue, as_mapping, as_sequence, as_str, at_path
from infrastructure.pipeline.fetch_missing.failed_lookups import (
    forget_failed_doi_lookups,
)
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.http_retry import lookup_json_async
from pipeline.sources.hal.fields import HAL_FIELDS_STR
from pipeline.sources.staging import upsert_staging


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

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        doi = dois[0]
        outcome = await lookup_json_async(
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
            not_found_statuses=frozenset(),
            label=f"DOI {doi}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return DoiBatchResult()
        docs = [as_mapping(d) for d in as_sequence(at_path(outcome, "response").get("docs"))]
        if not docs:
            # Réponse Solr valide, zéro doc : DOI confirmé absent de HAL.
            return DoiBatchResult(not_found=[doi])
        return DoiBatchResult(records=docs[:1])

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
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
            entry_mode="fetch_missing_doi",
        )
        forget_failed_doi_lookups(conn, "hal", [doi])
        return inserted


def hal_text_field(valeur: JsonValue) -> str | None:
    """Champ HAL, qui arrive en texte ou en liste de textes (convention Solr)."""
    if elements := as_sequence(valeur):
        return as_str(elements[0])
    return as_str(valeur)
