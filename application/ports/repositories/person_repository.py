"""Port PersonRepository — contrat d'accès à l'agrégat Person.

Défini par le domaine ; implémenté par infrastructure/repositories/
person_repository.py::PgPersonRepository (implémentation PostgreSQL
concrète). Toute autre implémentation respectant cette interface
(fake en mémoire pour tests, autre SGBD, etc.) est également acceptable.
"""

from enum import StrEnum
from typing import Protocol, TypedDict

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
