"""Adapter PostgreSQL pour l'agrégat Person.

Implémente le port `domain.ports.person_repository.PersonRepository`.
Le SQL est réparti par thème dans les sous-modules `_core`, `_identifiers`,
`_authorships`, `_name_forms` — la classe `PgPersonRepository` n'est qu'un
point d'agrégation qui borne la connexion et délègue.

Usage :
    repo = PgPersonRepository(conn)
    repo.set_rejected(person_id, True)
"""

from typing import TYPE_CHECKING

from sqlalchemy import Connection

from infrastructure.repositories.person_repository import (
    _authorships,
    _core,
    _identifiers,
    _name_forms,
)

if TYPE_CHECKING:
    from domain.persons.person import Person
    from domain.persons.person_identifier import PersonIdentifier


class PgPersonRepository:
    """Accès PostgreSQL à l'agrégat Person via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> "Person | None":
        return _core.find_by_id(self._conn, person_id)

    def create(self, last_name: str, first_name: str = "") -> int:
        return _core.create(self._conn, last_name, first_name)

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        _core.update_name(self._conn, person_id, last_name, first_name)

    def set_rejected(self, person_id: int, rejected: bool) -> None:
        _core.set_rejected(self._conn, person_id, rejected)

    # ── Fusion ─────────────────────────────────────────────────────

    def has_distinct_rh(self, id_a: int, id_b: int) -> bool:
        return _core.has_distinct_rh(self._conn, id_a, id_b)

    def merge_into(self, target_id: int, source_id: int) -> None:
        _core.merge_into(self._conn, target_id, source_id)

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(self, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
        return _core.mark_distinct(self._conn, person_id_a, person_id_b)

    # ── person_identifiers ─────────────────────────────────────────

    def find_identifier(self, id_type: str, id_value: str) -> "PersonIdentifier | None":
        return _identifiers.find_identifier(self._conn, id_type, id_value)

    def insert_identifier(self, ident: "PersonIdentifier") -> int:
        return _identifiers.insert_identifier(self._conn, ident)

    def update_identifier(self, ident: "PersonIdentifier") -> None:
        _identifiers.update_identifier(self._conn, ident)

    def remove_identifier(self, person_id: int, id_type: str, id_value: str) -> None:
        _identifiers.remove_identifier(self._conn, person_id, id_type, id_value)

    def update_identifier_status(self, ident_id: int, status: str) -> dict:
        return _identifiers.update_identifier_status(self._conn, ident_id, status)

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None:
        _identifiers.reassign_identifier(self._conn, ident_id, target_person_id)

    # ── source_authorships (liens personne ↔ authorship source) ────

    def link_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
    ) -> None:
        _authorships.link_authorship(self._conn, person_id, source, authorship_id)

    def unlink_authorship(self, person_id: int, source: str, authorship_id: int) -> None:
        _authorships.unlink_authorship(self._conn, person_id, source, authorship_id)

    def assign_orphan_sa(self, person_id: int, source: str, authorship_id: int) -> dict | None:
        return _authorships.assign_orphan_sa(self._conn, person_id, source, authorship_id)

    # ── Opérations atomiques pour le use case `assign_orphans` ────

    def assign_orphan_source_authorships_to_person(self, person_id: int, sa_ids: list[int]) -> int:
        return _authorships.assign_orphan_source_authorships_to_person(
            self._conn, person_id, sa_ids
        )

    def create_authorships_from_sources(
        self,
        person_id: int,
        sa_ids: list[int],
        source_priority: tuple[str, ...],
    ) -> None:
        _authorships.create_authorships_from_sources(self._conn, person_id, sa_ids, source_priority)

    def link_source_authorships_to_authorships(self, person_id: int, sa_ids: list[int]) -> None:
        _authorships.link_source_authorships_to_authorships(self._conn, person_id, sa_ids)

    def get_distinct_name_forms_from_source_authorships(self, sa_ids: list[int]) -> list[str]:
        return _authorships.get_distinct_name_forms_from_source_authorships(self._conn, sa_ids)

    def find_publication_id_for_source_authorship(
        self, source: str, authorship_id: int
    ) -> int | None:
        return _authorships.find_publication_id_for_source_authorship(
            self._conn, source, authorship_id
        )

    def insert_authorship_if_missing(self, publication_id: int, person_id: int) -> None:
        _authorships.insert_authorship_if_missing(self._conn, publication_id, person_id)

    def link_source_authorships_to_authorship_for_pair(
        self, publication_id: int, person_id: int
    ) -> None:
        _authorships.link_source_authorships_to_authorship_for_pair(
            self._conn, publication_id, person_id
        )

    def recompute_authorship_author_position_and_corresponding(
        self,
        publication_id: int,
        person_id: int,
        source_priority: tuple[str, ...],
        is_corresponding_priority: tuple[str, ...],
    ) -> None:
        _authorships.recompute_authorship_author_position_and_corresponding(
            self._conn,
            publication_id,
            person_id,
            source_priority,
            is_corresponding_priority,
        )

    def recompute_authorship_in_perimeter_and_structures(
        self,
        publication_id: int,
        person_id: int,
        sources: tuple[str, ...],
    ) -> None:
        _authorships.recompute_authorship_in_perimeter_and_structures(
            self._conn, publication_id, person_id, sources
        )

    def count_authorships_with_name_form(self, person_id: int, name_form: str) -> int:
        return _authorships.count_authorships_with_name_form(self._conn, person_id, name_form)

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        _name_forms.refresh_name_forms(self._conn, person_id, forms)

    def add_name_form(self, person_id: int, full_name: str, source: str | None = None) -> None:
        _name_forms.add_name_form(self._conn, person_id, full_name, source)

    def detach_name_form(self, person_id: int, name_form: str) -> None:
        _name_forms.detach_name_form(self._conn, person_id, name_form)
