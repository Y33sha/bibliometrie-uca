"""Port : SQL du normaliseur OpenAlex.

Implémenté par `infrastructure.queries.normalize_openalex.PgOpenalexNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class OpenalexNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur OpenAlex."""

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

    def count_openalex_table(self, conn: Connection, table: str) -> int: ...
