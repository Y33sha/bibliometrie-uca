"""Port : SQL du normaliseur ScanR.

Implémenté par `infrastructure.db.queries.normalize_scanr.PgScanrNormalizeQueries`.
"""

from typing import Any, Protocol


class ScanrNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur ScanR."""

    def upsert_scanr_source_publication(
        self,
        cur: Any,
        *,
        scanr_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: Any,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        topics: Any,
        cited_by_count: int | None,
        urls: list[str] | None,
    ) -> int: ...

    def upsert_scanr_source_person_by_idref(
        self,
        cur: Any,
        *,
        idref: str,
        full_name: str,
        last_name: str | None,
        first_name: str | None,
        orcid: str | None,
    ) -> int: ...

    def find_scanr_source_person_by_name(
        self, cur: Any, *, full_name: str, first_name: str | None
    ) -> int | None: ...

    def insert_scanr_source_person_new(
        self,
        cur: Any,
        *,
        full_name: str,
        last_name: str | None,
        first_name: str | None,
        orcid: str | None,
    ) -> int: ...

    def upsert_scanr_source_authorship(
        self,
        cur: Any,
        *,
        source_publication_id: int,
        source_person_id: int,
        author_position: int,
        roles: list[str] | None,
        raw_author_name: str | None,
    ) -> int: ...

    def get_scanr_publication_id(self, cur: Any, scanr_id: str) -> int | None: ...

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None: ...
