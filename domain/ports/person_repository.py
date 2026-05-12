"""Port PersonRepository — contrat d'accès à l'agrégat Person.

Défini par le domaine ; implémenté par infrastructure/repositories/
person_repository.py::PgPersonRepository (implémentation PostgreSQL
concrète). Toute autre implémentation respectant cette interface
(fake en mémoire pour tests, autre SGBD, etc.) est également acceptable.
"""

from typing import Any, Protocol


class PersonRepository(Protocol):
    """Contrat d'accès à l'agrégat Person (tables persons,
    person_identifiers, person_name_forms, distinct_persons, et
    certaines opérations sur source_authorships)."""

    # ── persons ────────────────────────────────────────────────────

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

    def add_identifier(
        self,
        person_id: int,
        id_type: str,
        id_value: str,
        source: str = "auto",
        status: str = "pending",
    ) -> None: ...

    def remove_identifier(self, person_id: int, id_type: str, id_value: str) -> None: ...

    def update_identifier_status(self, ident_id: int, status: str) -> dict[str, Any]: ...

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None: ...

    # ── source_authorships (liens personne ↔ authorship source) ────

    def link_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
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

    def insert_authorship_if_missing(self, publication_id: int, person_id: int) -> None: ...

    def link_source_authorships_to_authorship_for_pair(
        self,
        publication_id: int,
        person_id: int,
    ) -> None: ...

    def recompute_authorship_author_position_and_corresponding(
        self,
        publication_id: int,
        person_id: int,
        source_priority: tuple[str, ...],
        is_corresponding_priority: tuple[str, ...],
    ) -> None: ...

    def recompute_authorship_in_perimeter_and_structures(
        self,
        publication_id: int,
        person_id: int,
        sources: tuple[str, ...],
    ) -> None: ...

    def count_authorships_with_name_form(
        self,
        person_id: int,
        name_form: str,
    ) -> int: ...

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None: ...

    def add_name_form(
        self,
        person_id: int,
        full_name: str,
        source: str | None = None,
    ) -> None: ...

    def detach_name_form(self, person_id: int, name_form: str) -> None: ...
