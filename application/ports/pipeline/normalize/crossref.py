"""Port : SQL du normaliseur CrossRef.

Implémenté par ``infrastructure.db.queries.normalize_crossref.PgCrossrefNormalizeQueries``.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.json_types import JsonValue


class CrossrefNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur CrossRef."""

    def upsert_crossref_source_publication(
        self,
        conn: Connection,
        *,
        doi: str,
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
        cited_by_count: int | None,
        biblio: JsonValue,
        meta: JsonValue,
    ) -> int: ...

    def upsert_crossref_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        author_position: int,
        raw_author_name: str | None,
        source_data: JsonValue,
        person_identifiers: JsonValue,
    ) -> int: ...

    def get_crossref_publication_id(self, conn: Connection, doi: str) -> int | None: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
