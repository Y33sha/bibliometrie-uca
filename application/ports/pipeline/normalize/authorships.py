"""Port : SQL batch partagé pour l'écriture des `source_authorships`.

Implémenté par `infrastructure.queries.normalize_authorships.PgAuthorshipsBatchQueries`.

Les colonnes de `source_authorships` / `addresses` / `source_authorship_addresses`
sont identiques pour toutes les sources : seul le *parsing* du payload diffère.
Ce port regroupe les opérations d'écriture communes (batchs `executemany`),
paramétrées par `source`. Consommé par le writer partagé
`application.pipeline.normalize._authorships_batch.write_source_authorships`.
"""

from typing import Protocol, TypedDict

from sqlalchemy import Connection

from domain.types import JsonValue


class SourceAuthorshipBatchItem(TypedDict):
    """Ligne du batch upsert `source_authorships` (toutes sources).

    `author_name_normalized` est calculé en Python (`normalize_name_form`) par
    le writer. `source_data` / `source_structures` / `person_identifiers` sont
    nullables selon ce que la source fournit.
    """

    source: str
    spid: int
    author_position: int
    author_name_normalized: str
    is_corresponding: bool
    roles: list[str] | None
    source_structures: list[str] | None
    source_data: dict[str, JsonValue] | None
    raw_author_name: str
    person_identifiers: dict[str, JsonValue] | None


class AddressBatchItem(TypedDict):
    """Ligne du batch upsert `addresses` : texte brut + forme normalisée."""

    raw: str
    norm: str


class AddressCountryItem(TypedDict):
    """Propagation de pays sur une `addresses` : `{addr_id, countries}`."""

    addr_id: int
    countries: list[str]


class AuthorshipAddressItem(TypedDict):
    """Ligne du batch insert `source_authorship_addresses` : pivot (authorship, adresse)."""

    sa_id: int
    addr_id: int


class AuthorshipsBatchQueries(Protocol):
    """Opérations SQL batch partagées pour l'écriture des authorships."""

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None: ...

    def upsert_source_authorships_batch(
        self, conn: Connection, values: list[SourceAuthorshipBatchItem]
    ) -> None: ...

    def fetch_source_authorship_ids_by_position(
        self, conn: Connection, *, source: str, source_publication_id: int, positions: list[int]
    ) -> dict[int, int]: ...

    def upsert_addresses_batch(self, conn: Connection, values: list[AddressBatchItem]) -> None: ...

    def fetch_address_ids_by_raw_text(
        self, conn: Connection, raw_texts: list[str]
    ) -> dict[str, int]: ...

    def apply_address_countries_batch(
        self, conn: Connection, values: list[AddressCountryItem]
    ) -> None: ...

    def apply_address_suggested_countries_batch(
        self, conn: Connection, values: list[AddressCountryItem]
    ) -> None: ...

    def insert_source_authorship_addresses_batch(
        self, conn: Connection, values: list[AuthorshipAddressItem]
    ) -> None: ...
