"""Port : SQL du normaliseur Web of Science.

Implémenté par `infrastructure.db.queries.normalize_wos.PgWosNormalizeQueries`.
"""

from typing import Any, Protocol


class WosNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur WoS (batchs executemany)."""

    def upsert_wos_source_publication(
        self,
        conn: Any,
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

    def upsert_wos_source_structure(self, conn: Any, *, name: str, ror_id: str | None) -> int: ...

    def upsert_addresses_batch(self, conn: Any, values: list[dict[str, Any]]) -> None: ...

    def fetch_address_ids_by_raw_text(self, conn: Any, raw_texts: list[str]) -> dict[str, int]: ...

    def upsert_wos_source_authorships_batch(
        self, conn: Any, values: list[dict[str, Any]]
    ) -> None: ...

    def fetch_source_authorship_ids_by_position(
        self, conn: Any, *, source_publication_id: int, positions: list[int]
    ) -> dict[int, int]: ...

    def insert_source_authorship_addresses_batch(
        self, conn: Any, values: list[dict[str, int]]
    ) -> None: ...

    def get_wos_publication_id(self, conn: Any, ut: str) -> int | None: ...

    def fetch_wos_source_structures(self, conn: Any) -> list[tuple[str, int]]: ...

    def delete_wos_duplicate_authorships(self, conn: Any) -> int: ...

    def clear_source_authorships_for_publication(
        self, conn: Any, source_publication_id: int
    ) -> None: ...
