"""Port : SQL du normaliseur Web of Science.

Implémenté par `infrastructure.queries.normalize_wos.PgWosNormalizeQueries`.
"""

from typing import Protocol, TypedDict

from sqlalchemy import Connection

from domain.json_types import JsonValue


class WosAddressBatchItem(TypedDict):
    """Ligne du batch upsert `addresses` : texte brut + forme normalisée."""

    raw: str
    norm: str


class WosAuthorshipBatchItem(TypedDict):
    """Ligne du batch upsert `source_authorships` WoS.

    `source_structures` : noms d'institutions WoS (seul identifiant stable côté WoS, TEXT[]).
    `person_identifiers` : orcid + researcher_id en JSONB ; `daisng_id` non conservé.
    """

    spid: int
    author_position: int
    is_corresponding: bool
    author_name_normalized: str
    source_structures: list[str] | None
    roles: list[str] | None
    raw_author_name: str
    person_identifiers: dict[str, JsonValue] | None


class WosAuthorshipAddressItem(TypedDict):
    """Ligne du batch insert `source_authorship_addresses` : pivot (authorship, adresse)."""

    sa_id: int
    addr_id: int


class WosNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur WoS (batchs executemany)."""

    def upsert_wos_source_publication(
        self,
        conn: Connection,
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
        biblio: JsonValue,
        keywords: list[str] | None,
        topics: JsonValue,
        urls: list[str] | None,
        external_ids: JsonValue,
    ) -> int: ...

    def upsert_addresses_batch(
        self, conn: Connection, values: list[WosAddressBatchItem]
    ) -> None: ...

    def fetch_address_ids_by_raw_text(
        self, conn: Connection, raw_texts: list[str]
    ) -> dict[str, int]: ...

    def upsert_wos_source_authorships_batch(
        self, conn: Connection, values: list[WosAuthorshipBatchItem]
    ) -> None: ...

    def fetch_source_authorship_ids_by_position(
        self, conn: Connection, *, source_publication_id: int, positions: list[int]
    ) -> dict[int, int]: ...

    def insert_source_authorship_addresses_batch(
        self, conn: Connection, values: list[WosAuthorshipAddressItem]
    ) -> None: ...

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...
