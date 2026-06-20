"""Port : SQL du normaliseur HAL.

Implémenté par `infrastructure.queries.pipeline.normalize.hal.PgHalNormalizeQueries`.
"""

from datetime import date
from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class HalNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur HAL."""

    def upsert_hal_source_publication(
        self,
        conn: Connection,
        *,
        hal_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        hal_collections: list[str] | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        journal_id: int | None,
        oa_status: str | None,
        embargo_until: date | None,
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        topics: JsonValue,
        biblio: JsonValue,
        urls: list[str] | None,
    ) -> int: ...
