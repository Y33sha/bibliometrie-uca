"""Port PersonRepository — contrat d'accès à l'agrégat Person.

Défini par le domaine ; implémenté par infrastructure/repositories/
person_repository.py::PgPersonRepository (implémentation PostgreSQL
concrète). Toute autre implémentation respectant cette interface
(fake en mémoire pour tests, autre SGBD, etc.) est également acceptable.
"""

from enum import StrEnum
from typing import Any, Protocol, TypedDict

from domain.persons.person import Person
from domain.persons.person_identifier import PersonIdentifier


class AuthenticateOrcidOutcome(StrEnum):
    """Issue de l'authentification d'un ORCID par `authenticate_orcid`."""

    INSERTED = "inserted"  # l'ORCID n'existait pas, créé authentifié
    UPGRADED = "upgraded"  # déjà rattaché à cette personne, statut renforcé
    REASSIGNED = "reassigned"  # déplacé depuis une autre personne, puis authentifié
    NOOP = "noop"  # déjà authentifié sur cette personne


class IdentifierStatusRow(TypedDict):
    """Ligne renvoyée par `update_identifier_status` (changement de statut d'un
    identifiant ; `person_id` sert à l'audit)."""

    id: int
    status: str
    person_id: int


class NameFormStatusRow(TypedDict):
    """Ligne renvoyée par `update_name_form_status` (changement de statut d'une
    forme de nom). Alimente le DTO `NameFormStatusResponse`."""

    person_id: int
    name_form: str
    status: str


class PersonRepository(Protocol):
    """Contrat d'accès à l'agrégat Person (tables persons,
    person_identifiers, person_name_forms, distinct_persons, et
    certaines opérations sur source_authorships)."""

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> Person | None: ...

    def create(self, last_name: str, first_name: str = "") -> int: ...

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None: ...

    def set_rejected(self, person_id: int, rejected: bool) -> None: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def has_distinct_rh(self, id_a: int, id_b: int) -> bool: ...

    def merge_into(self, target_id: int, source_id: int) -> None: ...

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(
        self,
        person_id_a: int,
        person_id_b: int,
    ) -> tuple[int, int] | None: ...

    # ── person_identifiers ─────────────────────────────────────────

    def find_identifier(self, id_type: str, id_value: str) -> PersonIdentifier | None: ...

    def insert_identifier(self, ident: PersonIdentifier) -> int: ...

    def update_identifier(self, ident: PersonIdentifier) -> None: ...

    def remove_identifier(self, person_id: int, id_type: str, id_value: str) -> None: ...

    def update_identifier_status(self, ident_id: int, status: str) -> IdentifierStatusRow: ...

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None: ...

    def begin_authenticated_orcid_import(self) -> None: ...

    def authenticate_orcid(self, person_id: int, orcid: str) -> AuthenticateOrcidOutcome: ...

    # ── source_authorships (liens personne ↔ authorship source) ────

    def link_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
        resolution_mode: str,
    ) -> None: ...

    def unlink_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
    ) -> None: ...

    def assign_orphan_sa(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
    ) -> dict[str, Any] | None: ...

    # ── Opérations atomiques pour le use case `assign_orphans` ────
    # Orchestré dans `application/authorships/assign_orphans.py`.

    def assign_orphan_source_authorships_to_person(
        self,
        person_id: int,
        sa_ids: list[int],
    ) -> int: ...

    def create_authorships_from_sources(
        self,
        person_id: int,
        sa_ids: list[int],
        source_priority: tuple[str, ...],
    ) -> None: ...

    def link_source_authorships_to_authorships(
        self,
        person_id: int,
        sa_ids: list[int],
    ) -> None: ...

    def get_distinct_name_forms_from_source_authorships(
        self,
        sa_ids: list[int],
    ) -> list[str]: ...

    def find_publication_id_for_source_authorship(
        self,
        source: str,
        authorship_id: int,
    ) -> int | None: ...

    def find_publication_ids_for_source_authorships(
        self,
        sa_ids: list[int],
    ) -> list[int]:
        """Les `publication_id` distincts couverts par un lot de
        `source_authorships`. Sert au pré-contrôle de rejet en batch."""
        ...

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        """Détache (person_id → NULL) les source_authorships d'une personne portant
        une forme de nom donnée. Retourne le nombre de signatures détachées."""
        ...

    def insert_authorship_if_missing(self, publication_id: int, person_id: int) -> None: ...

    def link_source_authorships_to_authorship(
        self,
        publication_id: int,
        person_id: int,
    ) -> None: ...

    def recompute_authorship_author_position_and_corresponding(
        self,
        publication_id: int,
        person_id: int,
        source_priority: tuple[str, ...],
    ) -> None: ...

    def recompute_authorship_in_perimeter(
        self,
        publication_id: int,
        person_id: int,
        sources: tuple[str, ...],
    ) -> None: ...

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None: ...

    def add_name_form(
        self,
        person_id: int,
        full_name: str,
        source: str | None = None,
    ) -> None: ...

    def update_name_form_status(
        self, person_id: int, name_form: str, status: str
    ) -> NameFormStatusRow: ...

    def delete_orphan_name_forms_for_person(self, person_id: int) -> int:
        """Supprime les formes de nom attestées par une source qui ne sont plus
        portées par aucune `source_authorship` active de la personne (les
        formes calculées, source `persons`, sont préservées)."""
        ...
