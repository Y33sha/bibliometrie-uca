"""Port PersonRepository — contrat d'accès à l'agrégat Person.

Défini par le domaine ; implémenté par infrastructure/repositories/
person_repository.py::PgPersonRepository (implémentation PostgreSQL
concrète). Toute autre implémentation respectant cette interface
(fake en mémoire pour tests, autre SGBD, etc.) est également acceptable.
"""

from typing import Protocol


class PersonRepository(Protocol):
    """Contrat d'accès à l'agrégat Person (tables persons,
    person_identifiers, person_name_forms, distinct_persons, et
    certaines opérations sur source_authorships/source_persons)."""

    # ── persons ────────────────────────────────────────────────────

    def create(self, last_name: str, first_name: str = "") -> int: ...

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None: ...

    def set_rejected(self, person_id: int, rejected: bool) -> None: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def has_distinct_rh(self, id_a: int, id_b: int) -> bool: ...

    def merge_into(self, target_id: int, source_id: int) -> None: ...

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(
        self, person_id_a: int, person_id_b: int,
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

    def update_identifier_status(self, ident_id: int, status: str) -> dict: ...

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None: ...

    # ── source_authorships (liens personne ↔ authorship source) ────

    def link_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
        *,
        source_person_id: int | None = None,
        has_hal_person_id: bool = False,
    ) -> None: ...

    def unlink_authorship(
        self, person_id: int, source: str, authorship_id: int,
    ) -> None: ...

    def assign_orphan_sa(
        self, person_id: int, source: str, authorship_id: int,
    ) -> dict | None: ...

    def batch_assign_orphans(self, person_id: int, sa_ids: list[int]) -> int: ...

    def ensure_truth_authorship(
        self, person_id: int, source: str, authorship_id: int,
    ) -> None: ...

    def count_authorships_with_name_form(
        self, person_id: int, name_form: str,
    ) -> int: ...

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None: ...

    def add_name_form(
        self, person_id: int, full_name: str, source: str | None = None,
    ) -> None: ...

    def detach_name_form(self, person_id: int, name_form: str) -> None: ...
