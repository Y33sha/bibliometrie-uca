"""Port : SQL du normaliseur OpenAlex.

Implémenté par `infrastructure.db.queries.normalize_openalex.PgOpenalexNormalizeQueries`.
"""

from typing import Any, Protocol


class OpenalexNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur OpenAlex."""

    def fetch_publication_id_for_hal_source(self, cur: Any, hal_id: str) -> int | None: ...

    def upsert_openalex_source_publication(
        self,
        cur: Any,
        *,
        openalex_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: Any,
        urls: list[str] | None,
        cited_by_count: int | None,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        is_retracted: bool | None,
        biblio: Any,
        abstract: str | None,
        keywords: list[str] | None,
        topics_json: Any,
    ) -> int: ...

    def find_openalex_source_structure(self, cur: Any, openalex_id: str) -> int | None: ...

    def upsert_openalex_source_structure(
        self,
        cur: Any,
        *,
        openalex_id: str,
        name: str,
        ror_id: str | None,
        country: str | None,
        source_data: Any,
    ) -> int: ...

    def upsert_openalex_source_authorship(
        self,
        cur: Any,
        *,
        source_publication_id: int,
        source_person_id: int | None,
        author_position: int,
        source_struct_ids: list[int] | None,
        raw_author_name: str | None,
        is_corresponding: bool,
        identifiers: Any,
    ) -> int: ...

    def staging_has_openalex_doi(self, cur: Any, doi: str) -> bool: ...

    def get_openalex_publication_id(self, cur: Any, openalex_id: str) -> int | None: ...

    def count_openalex_table(self, cur: Any, table: str) -> int: ...

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None: ...
