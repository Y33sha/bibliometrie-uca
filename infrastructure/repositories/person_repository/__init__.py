"""Adapter PostgreSQL pour l'agrégat Person.

Implémente le port `application.ports.repositories.person_repository.PersonRepository`. Le SQL est réparti par thème dans les sous-modules `_core`, `_identifiers`, `_merge`, `_name_forms` — la classe `PgPersonRepository` n'est qu'un point d'agrégation qui borne la connexion et délègue.

Usage :
    repo = PgPersonRepository(conn)
    repo.set_exclusion(person_id, PersonExclusion.NOT_A_PERSON)
"""

from typing import TYPE_CHECKING

from sqlalchemy import Connection

from application.ports.repositories.person_repository import PersonRepository
from infrastructure.repositories.person_repository import (
    _core,
    _identifiers,
    _merge,
    _name_forms,
)
from infrastructure.repositories.person_repository._core import (
    create as create_person,
    update_name as update_person_name,
)
from infrastructure.repositories.person_repository._identifiers import (
    find_identifier as find_identifier,
    insert_identifier as insert_identifier,
    update_identifier as update_identifier,
)
from infrastructure.repositories.person_repository._merge import (
    person_without_decision_sql as person_without_decision_sql,
)
from infrastructure.repositories.person_repository._name_forms import (
    refresh_name_forms as refresh_name_forms,
)

__all__ = [
    "PgPersonRepository",
    "create_person",
    "find_identifier",
    "insert_identifier",
    "person_without_decision_sql",
    "refresh_name_forms",
    "update_identifier",
    "update_person_name",
]

if TYPE_CHECKING:
    from application.ports.repositories.person_repository import (
        IdentifierStatusRow,
        NameFormStatusRow,
    )
    from domain.persons.identifier_attribution import IdentifierAttribution
    from domain.persons.person import Person, PersonExclusion


class PgPersonRepository(PersonRepository):
    """Accès PostgreSQL à l'agrégat Person via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> "Person | None":
        return _core.find_by_id(self._conn, person_id)

    def create(self, last_name: str, first_name: str = "") -> int:
        return _core.create(self._conn, last_name, first_name)

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        _core.update_name(self._conn, person_id, last_name, first_name)

    def set_exclusion(self, person_id: int, exclusion: PersonExclusion | None) -> None:
        _core.set_exclusion(self._conn, person_id, exclusion)

    # ── Fusion ─────────────────────────────────────────────────────

    def ids_with_rh(self, person_ids: list[int]) -> set[int]:
        return _core.ids_with_rh(self._conn, person_ids)

    def merge_into(self, target_id: int, source_id: int) -> None:
        _merge.merge_into(self._conn, target_id, source_id)

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(self, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
        return _core.mark_distinct(self._conn, person_id_a, person_id_b)

    # ── person_identifiers ─────────────────────────────────────────

    def find_identifier(self, id_type: str, id_value: str) -> "IdentifierAttribution | None":
        return _identifiers.find_identifier(self._conn, id_type, id_value)

    def insert_identifier(self, ident: "IdentifierAttribution") -> int:
        return _identifiers.insert_identifier(self._conn, ident)

    def update_identifier(self, ident: "IdentifierAttribution") -> None:
        _identifiers.update_identifier(self._conn, ident)

    def update_identifier_status(self, ident_id: int, status: str) -> "IdentifierStatusRow":
        return _identifiers.update_identifier_status(self._conn, ident_id, status)

    def propagate_status_to_hal_accounts(self, ident_id: int, status: str) -> int:
        return _identifiers.propagate_status_to_hal_accounts(self._conn, ident_id, status)

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None:
        _identifiers.reassign_identifier(self._conn, ident_id, target_person_id)

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        _name_forms.refresh_name_forms(self._conn, person_id, forms)

    def add_name_form(self, person_id: int, full_name: str, source: str | None = None) -> None:
        _name_forms.add_name_form(self._conn, person_id, full_name, source)

    def update_name_form_status(
        self, person_id: int, name_form: str, status: str
    ) -> "NameFormStatusRow":
        return _name_forms.update_name_form_status(self._conn, person_id, name_form, status)

    def delete_orphan_name_forms_for_person(self, person_id: int) -> int:
        return _name_forms.delete_orphan_name_forms_for_person(self._conn, person_id)
