"""Port : SQL du normaliseur ScanR.

Implémenté par `infrastructure.db.queries.normalize_scanr.PgScanrNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.json_types import JsonValue


class ScanrNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur ScanR."""

    def upsert_scanr_source_publication(
        self,
        conn: Connection,
        *,
        scanr_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
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
        cited_by_count: int | None,
        urls: list[str] | None,
    ) -> int: ...

    def upsert_scanr_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        author_position: int,
        roles: list[str] | None,
        raw_author_name: str | None,
        person_identifiers: JsonValue,
    ) -> int: ...

    def get_scanr_publication_id(self, conn: Connection, scanr_id: str) -> int | None: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
