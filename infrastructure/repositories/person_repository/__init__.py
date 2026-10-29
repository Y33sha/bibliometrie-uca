"""Repository PostgreSQL de l'agrégat Person.

Implémente le port `application.ports.repositories.person_repository.PersonRepository`. Le SQL est réparti par thème dans les sous-modules `_core`, `_identifiers`, `_merge`, `_name_forms`. `PgPersonRepository` borne la connexion et délègue. Le renommage et l'attribution d'un identifiant y appliquent les règles de `domain.persons`, pour l'API comme pour la phase `persons`.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Connection

from application.ports.repositories.person_repository import PersonRepository
from domain.persons.identifier_attribution import (
    AttributionOutcome,
    AttributionResult,
    IdentifierAttribution,
    attribution_outcome,
)
from domain.persons.identifiers import (
    AttributionStatus,
    IdentifierOrigin,
    normalized_identifier_value,
)
from domain.persons.person import validated_name
from infrastructure.repositories.person_repository import (
    _core,
    _identifiers,
    _merge,
    _name_forms,
)
from infrastructure.repositories.person_repository._merge import (
    person_without_decision_sql as person_without_decision_sql,
)

__all__ = [
    "PgPersonRepository",
    "person_without_decision_sql",
]

if TYPE_CHECKING:
    from application.ports.repositories.person_repository import (
        IdentifierStatusRow,
        NameFormStatusRow,
    )
    from domain.persons.person import Person, PersonExclusion


class PgPersonRepository(PersonRepository):
    """Accès PostgreSQL à l'agrégat Person via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> Person | None:
        return _core.find_by_id(self._conn, person_id)

    def create(self, last_name: str, first_name: str = "") -> int:
        last_name, first_name = validated_name(last_name, first_name)
        person_id = _core.create(self._conn, last_name, first_name)
        _name_forms.refresh_canonical_name_forms(self._conn, person_id, last_name, first_name)
        return person_id

    def rename(self, person_id: int, last_name: str, first_name: str) -> tuple[str, str]:
        last_name, first_name = validated_name(last_name, first_name)
        _core.update_name(self._conn, person_id, last_name, first_name)
        _name_forms.refresh_canonical_name_forms(self._conn, person_id, last_name, first_name)
        return last_name, first_name

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

    def unmark_distinct(self, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
        return _core.unmark_distinct(self._conn, person_id_a, person_id_b)

    # ── person_identifiers ─────────────────────────────────────────

    def find_identifier(self, id_type: str, id_value: str) -> IdentifierAttribution | None:
        return _identifiers.find_identifier(self._conn, id_type, id_value)

    def insert_identifier(self, ident: IdentifierAttribution) -> int:
        return _identifiers.insert_identifier(self._conn, ident)

    def update_identifier(self, ident: IdentifierAttribution) -> None:
        _identifiers.update_identifier(self._conn, ident)

    def attribute_identifier(
        self, person_id: int, id_type: str, id_value: str, *, source: IdentifierOrigin
    ) -> AttributionResult:
        id_value = normalized_identifier_value(id_type, id_value)
        existing = self.find_identifier(id_type, id_value)
        outcome = attribution_outcome(existing, person_id)
        if outcome is AttributionOutcome.ADDED:
            self.insert_identifier(
                IdentifierAttribution(
                    id=None,
                    person_id=person_id,
                    id_type=id_type,
                    id_value=id_value,
                    status=AttributionStatus.PENDING,
                    source=source,
                )
            )
        elif existing is not None and outcome is AttributionOutcome.REASSIGNED:
            existing.reattribute_to(person_id, source=source)
            self.update_identifier(existing)
        return AttributionResult(outcome, id_value, existing)

    def update_identifier_status(self, ident_id: int, status: str) -> IdentifierStatusRow:
        return _identifiers.update_identifier_status(self._conn, ident_id, status)

    def propagate_status_to_hal_accounts(self, ident_id: int, status: str) -> int:
        return _identifiers.propagate_status_to_hal_accounts(self._conn, ident_id, status)

    def mark_contributions_of_rejected_identifiers(self, person_id: int) -> int:
        return _identifiers.mark_contributions_of_rejected_identifiers(self._conn, person_id)

    # ── person_name_forms ──────────────────────────────────────────

    def add_name_form(self, person_id: int, full_name: str, source: str | None = None) -> None:
        _name_forms.add_name_form(self._conn, person_id, full_name, source)

    def update_name_form_status(
        self, person_id: int, name_form: str, status: str
    ) -> NameFormStatusRow:
        return _name_forms.update_name_form_status(self._conn, person_id, name_form, status)

    def delete_orphan_name_forms_for_person(self, person_id: int) -> int:
        return _name_forms.delete_orphan_name_forms_for_person(self._conn, person_id)
