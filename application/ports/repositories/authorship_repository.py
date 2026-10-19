"""Port AuthorshipRepository — accès aux tables `authorships` et `source_authorships`.

Un seul port pour les deux : leurs opérations sont étroitement couplées.
"""

from datetime import datetime
from typing import Protocol, TypedDict


class AuthorshipPersonRow(TypedDict):
    """Ligne renvoyée par `get_authorship_person` : identité d'une ligne consolidée `authorships`."""

    id: int
    person_id: int
    publication_id: int


class AssignedSignatureRow(TypedDict):
    """Ligne renvoyée par `assign_orphan_source_authorship` : source et forme de nom de la signature rattachée."""

    source: str
    author_name_normalized: str | None


class AuthorshipRepository(Protocol):
    """Contrat d'accès aux tables authorships et source_authorships."""

    # ── source_authorships : lien personne ↔ signature ─────────────

    def assign_orphan_source_authorship(
        self,
        person_id: int,
        source_authorship_id: int,
    ) -> AssignedSignatureRow | None:
        """Pose `person_id` sur une signature source orpheline. Retourne `{source, author_name_normalized}`, ou `None` si la signature n'existe pas ou porte déjà un `person_id` — `find_source_authorship_owner` départage."""
        ...

    def find_source_authorship_owner(self, source_authorship_id: int) -> int | None:
        """`person_id` d'une signature source. `None` si elle est orpheline ou n'existe pas."""
        ...

    def get_distinct_name_forms_from_source_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> list[str]:
        """Les `author_name_normalized` distincts observés dans le lot de signatures."""
        ...

    def find_publication_id_for_source_authorship(
        self,
        source_authorship_id: int,
    ) -> int | None:
        """`publication_id` d'une signature, ou `None` si elle n'existe pas ou n'est pas rattachée à une publication."""
        ...

    def find_publication_ids_for_source_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> list[int]:
        """Les `publication_id` distincts couverts par un lot de signatures. Sert au pré-contrôle de rejet en batch."""
        ...

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        """Détache (person_id → NULL) les signatures d'une personne portant une forme de nom donnée, sauf celles que l'admin a épinglées sur elle. Retourne le nombre de signatures détachées."""
        ...

    # ── authorships ────────────────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> AuthorshipPersonRow | None:
        """La ligne `authorships` (`id`, `person_id`, `publication_id`), ou `None` si l'id n'existe pas."""
        ...

    def reject_authorship(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) sur chaque notice de la publication (`rejected_authorships`) : le rejet suit les notices quand la réconciliation regroupe autrement les publications. Idempotent."""
        ...

    def find_rejected_authorship(self, publication_id: int, person_id: int) -> datetime | None:
        """Date du premier rejet de la personne sur une notice de la publication, ou None si la publication n'est pas rejetée pour elle."""
        ...

    def delete_rejected_authorship(self, publication_id: int, person_id: int) -> None:
        """Lève le rejet d'une paire (publication, personne) sur toutes les notices de la publication. Idempotent."""
        ...

    def detach_rejected_pair(self, publication_id: int, person_id: int) -> int:
        """Détache toutes les signatures de la personne sur cette publication, où elle est rejetée, et retire leurs épinglages. Retourne le nombre de signatures détachées."""
        ...

    def delete_orphan_authorships_for_person(self, person_id: int) -> int:
        """Supprime les lignes consolidées de la personne dépourvues de toute signature source active. Retourne le nombre supprimé."""
        ...

    # ── confirmed_authorships (épinglage admin, must-link grain signature) ──

    def pin_authorships(self, source_authorship_ids: list[int], person_id: int) -> None:
        """Épingle des signatures à une personne dans `confirmed_authorships` (résolution admin d'orphelines). Upsert par signature : le dernier épinglage l'emporte."""
        ...

    # ── Propagation UCA depuis les adresses ────────────────────────

    def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        """Ids des signatures liées à l'une des adresses données (via `source_authorship_addresses`)."""
        ...

    # ── Recomposition d'une authorship depuis ses signatures ───────

    def consolidate_authorships(self, person_id: int, publication_ids: list[int]) -> None:
        """Crée et recompose les lignes consolidées de la personne sur ces publications, depuis ses signatures, par les requêtes de la phase `authorships`."""
        ...
