"""Adapter PostgreSQL async pour l'agrégat Person.

Miroir async de infrastructure/repositories/person_repository/. Même
découpage par thème dans les sous-modules ; la classe
`PgAsyncPersonRepository` délègue au curseur async.
"""

from typing import Any

from infrastructure.repositories.async_person_repository import (
    _authorships,
    _core,
    _identifiers,
    _name_forms,
)


class PgAsyncPersonRepository:
    """Accès PostgreSQL async à l'agrégat Person."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── persons ────────────────────────────────────────────────────

    async def create(self, last_name: str, first_name: str = "") -> int:
        return await _core.create(self._cur, last_name, first_name)

    async def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        await _core.update_name(self._cur, person_id, last_name, first_name)

    async def set_rejected(self, person_id: int, rejected: bool) -> None:
        await _core.set_rejected(self._cur, person_id, rejected)

    # ── Fusion ─────────────────────────────────────────────────────

    async def has_distinct_rh(self, id_a: int, id_b: int) -> bool:
        return await _core.has_distinct_rh(self._cur, id_a, id_b)

    async def merge_into(self, target_id: int, source_id: int) -> None:
        await _core.merge_into(self._cur, target_id, source_id)

    # ── distinct_persons ───────────────────────────────────────────

    async def mark_distinct(self, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
        return await _core.mark_distinct(self._cur, person_id_a, person_id_b)

    # ── person_identifiers ─────────────────────────────────────────

    async def add_identifier(
        self,
        person_id: int,
        id_type: str,
        id_value: str,
        source: str = "auto",
        status: str = "pending",
    ) -> None:
        await _identifiers.add_identifier(self._cur, person_id, id_type, id_value, source, status)

    async def remove_identifier(self, person_id: int, id_type: str, id_value: str) -> None:
        await _identifiers.remove_identifier(self._cur, person_id, id_type, id_value)

    async def update_identifier_status(self, ident_id: int, status: str) -> dict:
        return await _identifiers.update_identifier_status(self._cur, ident_id, status)

    async def reassign_identifier(self, ident_id: int, target_person_id: int) -> None:
        await _identifiers.reassign_identifier(self._cur, ident_id, target_person_id)

    # ── source_authorships (liens personne ↔ authorship source) ────

    async def link_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
        *,
        source_person_id: int | None = None,
        has_hal_person_id: bool = False,
    ) -> None:
        await _authorships.link_authorship(
            self._cur,
            person_id,
            source,
            authorship_id,
            source_person_id=source_person_id,
            has_hal_person_id=has_hal_person_id,
        )

    async def unlink_authorship(self, person_id: int, source: str, authorship_id: int) -> None:
        await _authorships.unlink_authorship(self._cur, person_id, source, authorship_id)

    async def assign_orphan_sa(
        self, person_id: int, source: str, authorship_id: int
    ) -> dict | None:
        return await _authorships.assign_orphan_sa(self._cur, person_id, source, authorship_id)

    async def batch_assign_orphans(self, person_id: int, sa_ids: list[int]) -> int:
        return await _authorships.batch_assign_orphans(self._cur, person_id, sa_ids)

    async def ensure_truth_authorship(
        self, person_id: int, source: str, authorship_id: int
    ) -> None:
        await _authorships.ensure_truth_authorship(self._cur, person_id, source, authorship_id)

    async def count_authorships_with_name_form(self, person_id: int, name_form: str) -> int:
        return await _authorships.count_authorships_with_name_form(self._cur, person_id, name_form)

    # ── person_name_forms ──────────────────────────────────────────

    async def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        await _name_forms.refresh_name_forms(self._cur, person_id, forms)

    async def add_name_form(
        self, person_id: int, full_name: str, source: str | None = None
    ) -> None:
        await _name_forms.add_name_form(self._cur, person_id, full_name, source)

    async def detach_name_form(self, person_id: int, name_form: str) -> None:
        await _name_forms.detach_name_form(self._cur, person_id, name_form)
