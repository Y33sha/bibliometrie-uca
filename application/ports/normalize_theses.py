"""Port : SQL du normaliseur theses.fr.

Implémenté par `infrastructure.db.queries.normalize_theses.PgThesesNormalizeQueries`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class ThesesNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur theses.fr."""

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None: ...

    def merge_publication_meta(
        self, conn: Connection, publication_id: int, meta_json: Any
    ) -> None: ...

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
        external_ids: Any,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        keywords: list[str] | None,
        topics_json: Any,
        source_meta_json: Any,
    ) -> int: ...

    def upsert_theses_source_person_by_ppn(
        self,
        conn: Connection,
        *,
        ppn: str,
        full_name: str,
    ) -> int: ...

    def upsert_theses_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        source_person_id: int | None,
        author_position: int | None,
        roles: list[str],
        raw_author_name: str,
        identifiers: Any,
    ) -> int: ...

    def get_theses_publication_id(self, conn: Connection, theses_id: str) -> int | None: ...

    def count_theses_table(self, conn: Connection, table: str) -> int: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
