"""Port : SQL du normaliseur HAL.

Implémenté par `infrastructure.queries.normalize_hal.PgHalNormalizeQueries`.
"""

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
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        topics: JsonValue,
        biblio: JsonValue,
        urls: list[str] | None,
    ) -> int: ...

    def upsert_hal_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        author_position: int,
        source_structures: list[str] | None,
        raw_author_name: str,
        is_corresponding: bool,
        roles: list[str] | None,
        person_identifiers: JsonValue,
    ) -> int: ...

    def staging_has_hal_doi(self, conn: Connection, doi: str) -> bool: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
