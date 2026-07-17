"""Port : SQL batch partagé pour l'écriture des `source_authorships`.

Implémenté par `infrastructure.queries.pipeline.normalize.authorships.PgAuthorshipsBatchQueries`.

Les colonnes de `source_authorships` / `addresses` / `source_authorship_addresses` sont identiques pour toutes les sources : seul le *parsing* du payload diffère.
Ce port regroupe les opérations d'écriture communes (batchs `executemany`), paramétrées par `source`. Consommé par le writer partagé `application.pipeline.normalize._authorships_batch.write_source_authorships`.
"""

from collections.abc import Mapping
from typing import Protocol, TypedDict

from sqlalchemy import Connection

from domain.types import JsonValue


class SourceAuthorshipItem(TypedDict):
    """Une signature à écrire dans `source_authorships` (toutes sources).

    `author_name_normalized` est calculé en Python (`normalize_name_form`) par le writer. `person_identifiers` est nullable selon ce que la source fournit.

    `author_position` est nul pour les signatures qui n'occupent pas de rang d'auteur — les rôles non-auteur d'une thèse (direction, rapport, jury, présidence). La contrainte `(source_publication_id, author_position)` les tolère, les `NULL` étant distincts entre eux.
    """

    source: str
    source_publication_id: int
    author_position: int | None
    author_name_normalized: str
    is_corresponding: bool
    roles: list[str] | None
    raw_author_name: str
    person_identifiers: Mapping[str, JsonValue] | None
    """Lu seulement (sérialisé en JSONB) : `Mapping` accepte les dictionnaires plus étroits que les sources produisent, tel le `dict[str, str]` des identifiants de thèse."""


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
        self, conn: Connection, values: list[SourceAuthorshipItem]
    ) -> None: ...

    def upsert_source_authorship(self, conn: Connection, item: SourceAuthorshipItem) -> int:
        """Écrit une signature seule et retourne son id.

        Sert les sources dont les signatures n'ont pas toutes un rang d'auteur : le writer batch remappe les ids par `author_position`, ce que des positions nulles ne permettent pas.
        """
        ...

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
