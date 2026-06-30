"""Port AuthorshipRepository — contrat d'accès aux agrégats Authorship.

Un seul port pour `authorships` et `source_authorships` car leurs
opérations sont étroitement couplées.
"""

from datetime import datetime
from typing import Any, Protocol


class AuthorshipRepository(Protocol):
    """Contrat d'accès aux tables authorships et source_authorships."""

    # ── authorships ────────────────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> dict[str, Any] | None: ...

    def reject_authorship(self, publication_id: int, person_id: int) -> None: ...

    def find_rejected_authorship(self, publication_id: int, person_id: int) -> datetime | None:
        """Date du rejet de la paire (publication, personne) dans
        `rejected_authorships`, ou None si la paire n'est pas rejetée."""
        ...

    def delete_rejected_authorship(self, publication_id: int, person_id: int) -> None:
        """Lève le rejet d'une paire (publication, personne) : la retire de
        `rejected_authorships`. Idempotent."""
        ...

    def unlink_all_source_authorships_for_pair(
        self,
        publication_id: int,
        person_id: int,
    ) -> int: ...

    def delete_authorship(self, authorship_id: int) -> None: ...

    def delete_orphan_authorships_for_person(self, person_id: int) -> int: ...

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

    def propagate_in_perimeter_to_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None: ...
