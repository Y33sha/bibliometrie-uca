"""Port : lectures et réinitialisations de la phase personnes (reset, match, create, purge).

Implémenté par `infrastructure.queries.pipeline.persons_create.PgPersonsCreateQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class BareUnlinkedAuthorship(NamedTuple):
    """Projection SQL brute : `source_authorships` non rattaché à une personne.

    `roles` non vide en pratique uniquement pour theses (auteur vs directeur).

    `in_perimeter` reflète la détection UCA de la source sur cette signature.
    Les candidats `in_perimeter = FALSE` ne sont rattachables que par les
    barreaux non-nominaux de la cascade (identifiants forts, cross-source) —
    le matching/création par forme de nom reste réservé au périmètre UCA
    (cf. `decide_name_form_outcome` et l'orchestrateur).
    """

    authorship_id: int
    source: str
    full_name: str
    author_name_normalized: str | None
    orcid: str | None
    hal_person_id: str | None
    idref: str | None
    roles: list[str] | None
    publication_id: int | None
    author_position: int
    in_perimeter: bool
    # `person_id` courant si la signature est déjà liée en cross-source et re-jugée ce run ; `None` pour une signature non liée. Sert à diffuser l'écriture (no-op / update) et le détachement des sans-appui.
    current_person_id: int | None


class LinkedAuthorshipRow(NamedTuple):
    """Projection SQL : `source_authorships` déjà rattaché à une personne, toutes sources confondues. Sert au matching cross-source par `(publication_id, author_position)`."""

    person_id: int
    author_position: int
    publication_id: int
    full_name: str
    source: str


class PersonsCreateQueries(Protocol):
    """Opérations SQL pour le rattachement des authorships aux personnes."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]: ...

    def fetch_out_of_perimeter_candidates(
        self, conn: Connection
    ) -> list[BareUnlinkedAuthorship]: ...

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]: ...

    def fetch_cross_source_linked(self, conn: Connection) -> list[BareUnlinkedAuthorship]: ...

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]: ...

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]: ...

    def fetch_hal_account_to_person_map(
        self, conn: Connection
    ) -> dict[str, tuple[int, str, str]]: ...

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]: ...

    def fetch_name_form_status_map(self, conn: Connection) -> dict[tuple[str, int], str]: ...

    def fetch_rejected_person_ids_by_pub(self, conn: Connection) -> dict[int, frozenset[int]]: ...

    def fetch_identifier_consensus(
        self, conn: Connection, id_type: str, values: list[str]
    ) -> dict[str, str]: ...

    def fetch_person_name_forms(
        self, conn: Connection, person_ids: list[int]
    ) -> dict[int, tuple[str, str, list[str]]]: ...

    def fetch_identifier_owners(
        self, conn: Connection, id_type: str
    ) -> dict[str, tuple[int, str]]: ...

    def fetch_identifier_bearer_persons(
        self, conn: Connection, id_type: str, sources: tuple[str, ...] | None = None
    ) -> list[tuple[str, int]]: ...

    def null_identifier_signatures(
        self, conn: Connection, id_type: str, id_value: str, old_owner_person_id: int
    ) -> int: ...

    def reorphan_ambiguous_nominal(self, conn: Connection) -> int: ...

    def detach_authorships(self, conn: Connection, authorship_ids: list[int]) -> int: ...

    def delete_empty_persons(self, conn: Connection) -> int: ...
