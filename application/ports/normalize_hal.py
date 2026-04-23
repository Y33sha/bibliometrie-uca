"""Port : SQL du normaliseur HAL.

Implémenté par `infrastructure.db.queries.normalize_hal.PgHalNormalizeQueries`.
"""

from typing import Any, Protocol


class HalNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur HAL."""

    def upsert_hal_source_publication(
        self,
        cur: Any,
        *,
        hal_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        hal_collections: list[str] | None,
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
        biblio: Any,
        urls: list[str] | None,
    ) -> int: ...

    def upsert_hal_source_person(
        self,
        cur: Any,
        *,
        source_id: str,
        full_name: str,
        last_name: str,
        first_name: str | None,
        orcid: str | None,
        idref: str | None,
        source_ids_json: Any,
    ) -> int: ...

    def find_hal_source_person_nokey(
        self, cur: Any, *, full_name: str, first_name: str | None
    ) -> int | None: ...

    def enrich_hal_source_person(
        self,
        cur: Any,
        *,
        source_person_id: int,
        orcid: str | None,
        idref: str | None,
        source_ids_json: Any,
    ) -> None: ...

    def insert_hal_source_person_new(
        self,
        cur: Any,
        *,
        full_name: str,
        last_name: str,
        first_name: str | None,
        orcid: str | None,
        idref: str | None,
        source_ids_json: Any,
    ) -> int: ...

    def upsert_hal_source_structure(self, cur: Any, *, source_id: str, name: str) -> int: ...

    def fetch_hal_source_structure_ids(self, cur: Any, source_ids: list[str]) -> list[int]: ...

    def upsert_hal_source_authorship(
        self,
        cur: Any,
        *,
        source_publication_id: int,
        source_person_id: int,
        author_position: int,
        source_struct_ids: list[int] | None,
        raw_author_name: str,
        is_corresponding: bool,
        roles: list[str] | None,
    ) -> int: ...

    def staging_has_hal_doi(self, cur: Any, doi: str) -> bool: ...

    def get_hal_publication_id(self, cur: Any, hal_id: str) -> int | None: ...

    def fetch_hal_source_structures_for_cache(self, cur: Any) -> list[tuple[str, int, str]]: ...

    def delete_hal_duplicate_authorship_addresses(self, cur: Any) -> None: ...

    def delete_hal_duplicate_authorships(self, cur: Any) -> int: ...

    def delete_hal_orphan_source_persons(self, cur: Any) -> int: ...
