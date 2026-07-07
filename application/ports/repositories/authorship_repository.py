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

    # ── confirmed_authorships (épinglage admin, must-link grain signature) ──

    def pin_authorships(self, source_authorship_ids: list[int], person_id: int) -> None:
        """Épingle des signatures à une personne dans `confirmed_authorships`
        (résolution admin d'orphelines). Upsert : ré-épingler une signature vers
        une autre personne remplace l'épinglage."""
        ...

    def unpin_authorships_for_pair(self, publication_id: int, person_id: int) -> int:
        """Retire les épinglages des signatures de la paire (publication, personne)
        — détachement admin. Retourne le nombre d'épinglages retirés."""
        ...

    def unpin_authorships_for_name_form(self, person_id: int, name_form: str) -> int:
        """Retire les épinglages des signatures d'une personne portant une forme de
        nom donnée — rejet de forme. Retourne le nombre d'épinglages retirés."""
        ...

    def enforce_confirmed_authorships(self) -> int:
        """Réapplique les épinglages : pose `source_authorships.person_id` = personne
        épinglée là où ils divergent. Lecture pipeline du must-link (une signature
        épinglée reste sur sa personne). Retourne le nombre de signatures recalées."""
        ...

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
