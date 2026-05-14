"""Port : SQL du normaliseur theses.fr.

Implémenté par `infrastructure.db.queries.normalize_theses.PgThesesNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.json_types import JsonValue


class ThesesNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur theses.fr."""

    def upsert_theses_source_publication(
        self,
        conn: Connection,
        *,
        theses_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        keywords: list[str] | None,
        topics_json: JsonValue,
        source_meta_json: JsonValue,
    ) -> int: ...

    def upsert_theses_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        author_position: int | None,
        roles: list[str],
        raw_author_name: str,
        person_identifiers: JsonValue,
    ) -> int: ...

    def count_theses_table(self, conn: Connection, table: str) -> int: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
