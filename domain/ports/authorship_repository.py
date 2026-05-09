"""Ports AuthorshipRepository / AsyncAuthorshipRepository — contrat
d'accès aux agrégats Authorship.

Un seul port pour `authorships` et `source_authorships` car leurs
opérations sont étroitement couplées. Deux variantes :
- `AsyncAuthorshipRepository` : routers async.
- `AuthorshipRepository` : routers sync (chantier sync-async-deduplication).
"""

from typing import Protocol


class AsyncAuthorshipRepository(Protocol):
    """Contrat d'accès aux tables authorships et source_authorships."""

    # ── authorships (vérité) ───────────────────────────────────────

    async def get_authorship_person(self, authorship_id: int) -> dict | None: ...

    async def mark_authorship_excluded(self, authorship_id: int) -> dict: ...

    async def detach_source_authorships_for_person(
        self,
        authorship_id: int,
        person_id: int,
    ) -> None: ...

    async def delete_authorship(self, authorship_id: int) -> None: ...

    async def delete_orphan_authorships_for_person(self, person_id: int) -> int: ...

    # ── source_authorships ─────────────────────────────────────────

    async def set_source_authorship_excluded(
        self,
        source_authorship_id: int,
        source: str,
        excluded: bool,
    ) -> bool: ...

    async def get_source_authorship_truth_id(
        self,
        source_authorship_id: int,
        source: str,
    ) -> int | None: ...

    async def clear_source_authorship_fk(
        self,
        source_authorship_id: int,
        source: str,
    ) -> None: ...

    async def has_active_source_attestation(self, truth_id: int) -> bool: ...

    # ── Propagation UCA depuis les adresses ────────────────────────

    async def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]: ...

    async def recompute_in_perimeter_on_source_authorships(
        self,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None: ...

    async def propagate_in_perimeter_to_truth_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None: ...


class AuthorshipRepository(Protocol):
    """Variante sync d'`AsyncAuthorshipRepository`."""

    # ── authorships (vérité) ───────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> dict | None: ...

    def mark_authorship_excluded(self, authorship_id: int) -> dict: ...

    def detach_source_authorships_for_person(
        self,
        authorship_id: int,
        person_id: int,
    ) -> None: ...

    def delete_authorship(self, authorship_id: int) -> None: ...

    def delete_orphan_authorships_for_person(self, person_id: int) -> int: ...

    # ── source_authorships ─────────────────────────────────────────

    def set_source_authorship_excluded(
        self,
        source_authorship_id: int,
        source: str,
        excluded: bool,
    ) -> bool: ...

    def get_source_authorship_truth_id(
        self,
        source_authorship_id: int,
        source: str,
    ) -> int | None: ...

    def clear_source_authorship_fk(
        self,
        source_authorship_id: int,
        source: str,
    ) -> None: ...

    def has_active_source_attestation(self, truth_id: int) -> bool: ...

    # ── Propagation UCA depuis les adresses ────────────────────────

    def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]: ...

    def recompute_in_perimeter_on_source_authorships(
        self,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None: ...

    def propagate_in_perimeter_to_truth_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None: ...
