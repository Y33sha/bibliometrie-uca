"""Port : SQL du normaliseur Web of Science.

Implémenté par `infrastructure.db.queries.normalize_wos.PgWosNormalizeQueries`.
"""

from typing import Any, Protocol


class WosNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur WoS (batchs execute_values)."""

    def upsert_wos_source_publication(
        self,
        cur: Any,
        *,
        ut: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        cited_by_count: int | None,
        biblio: Any,
        keywords: list[str] | None,
        topics: Any,
        urls: list[str] | None,
        external_ids: Any,
    ) -> int: ...

    def upsert_wos_source_person(
        self,
        cur: Any,
        *,
        daisng_id: str,
        full_name: str,
        last_name: str | None,
        first_name: str | None,
        orcid: str | None,
        source_ids_json: Any,
    ) -> int: ...

    def upsert_wos_source_persons_batch(
        self, cur: Any, values: list[tuple[Any, ...]]
    ) -> list[tuple[int, str]]: ...

    def upsert_wos_source_structure(self, cur: Any, *, name: str, ror_id: str | None) -> int: ...

    def upsert_addresses_batch(self, cur: Any, values: list[tuple[str, str]]) -> None: ...

    def fetch_address_ids_by_raw_text(self, cur: Any, raw_texts: list[str]) -> dict[str, int]: ...

    def upsert_wos_source_authorships_batch(
        self, cur: Any, values: list[tuple[Any, ...]]
    ) -> None: ...

    def fetch_source_authorship_ids(
        self, cur: Any, *, source_publication_id: int, source_person_ids: list[int]
    ) -> dict[int, int]: ...

    def insert_source_authorship_addresses_batch(
        self, cur: Any, values: list[tuple[int, int]]
    ) -> None: ...

    def get_wos_publication_id(self, cur: Any, ut: str) -> int | None: ...

    def fetch_wos_source_structures(self, cur: Any) -> list[tuple[str, int]]: ...

    def fetch_wos_source_persons_with_daisng(self, cur: Any) -> list[tuple[str, int]]: ...

    def delete_wos_duplicate_authorships(self, cur: Any) -> int: ...

    def delete_wos_orphan_legacy_source_persons(self, cur: Any) -> int: ...

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None: ...
