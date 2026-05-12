"""Port : SQL du normaliseur OpenAlex.

Implémenté par `infrastructure.db.queries.normalize_openalex.PgOpenalexNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.json_types import JsonValue


class OpenalexNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur OpenAlex."""

    def fetch_publication_id_for_hal_source(self, conn: Connection, hal_id: str) -> int | None: ...

    def upsert_openalex_source_publication(
        self,
        conn: Connection,
        *,
        openalex_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        urls: list[str] | None,
        cited_by_count: int | None,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        is_retracted: bool | None,
        biblio: JsonValue,
        abstract: str | None,
        keywords: list[str] | None,
        topics_json: JsonValue,
    ) -> int: ...

    def find_openalex_source_structure(self, conn: Connection, openalex_id: str) -> int | None: ...

    def upsert_openalex_source_structure(
        self,
        conn: Connection,
        *,
        openalex_id: str,
        name: str,
        ror_id: str | None,
        country: str | None,
        source_data: JsonValue,
    ) -> int: ...

    def upsert_openalex_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        source_person_id: int | None,
        author_position: int,
        source_struct_ids: list[int] | None,
        raw_author_name: str | None,
        is_corresponding: bool,
        identifiers: JsonValue,
    ) -> int: ...

    def staging_has_openalex_doi(self, conn: Connection, doi: str) -> bool: ...

    def get_openalex_publication_id(self, conn: Connection, openalex_id: str) -> int | None: ...

    def count_openalex_table(self, conn: Connection, table: str) -> int: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
