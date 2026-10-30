"""Port ContributionRepository : accès aux contributions (`contributions`) et aux contributions sources (`source_contributions`)."""

from datetime import datetime
from typing import Protocol, TypedDict


class ContributionRow(TypedDict):
    """Clés d'une contribution, renvoyées par `find_contributions`."""

    id: int
    person_id: int | None
    publication_id: int


class AlignedSourceContributionRow(TypedDict):
    """Contribution source d'une contribution, avec sa source et sa forme de nom, renvoyée par `find_aligned_source_contributions`."""

    source_contribution_id: int
    source: str
    author_name_normalized: str | None


class ContributionRepository(Protocol):
    """Contrat d'accès aux contributions et aux contributions sources."""

    # ── source_contributions ─────────────

    def find_publication_id_for_source_contribution(
        self,
        source_contribution_id: int,
    ) -> int | None:
        """Renvoie la publication d'une contribution source, ou `None` si la contribution source est absente ou sans publication."""
        ...

    # ── Contributions ─────────────

    def mark_contributions_for_name_form(self, person_id: int, name_form: str) -> int:
        """Marque pour redécision les contributions de la personne rattachées par le nom (`name`, `compatible_name`), à contribution source contenant la forme de nom. Renvoie le nombre de contributions marquées."""
        ...

    def find_contributions(self, contribution_ids: list[int]) -> list[ContributionRow]:
        """Renvoie les contributions demandées existantes."""
        ...

    def manual_contributions_of_person(
        self, person_id: int, publication_ids: list[int]
    ) -> dict[int, int]:
        """Renvoie les contributions `manual` de la personne sur les publications données, indexées par publication."""
        ...

    def find_aligned_source_contributions(
        self, contribution_ids: list[int]
    ) -> list[AlignedSourceContributionRow]:
        """Renvoie les contributions sources des contributions données, avec leur source et leur forme de nom."""
        ...

    def reject_contribution(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) sur chaque enregistrement source de la publication (`rejected_contributions`). Le rejet suit donc les enregistrements sources quand la réconciliation regroupe autrement les publications. Idempotent."""
        ...

    def find_rejected_contribution(self, publication_id: int, person_id: int) -> datetime | None:
        """Renvoie la date du premier rejet de la personne sur un enregistrement source de la publication, ou `None` sans rejet."""
        ...

    def delete_rejected_contribution(self, publication_id: int, person_id: int) -> None:
        """Lève le rejet d'une paire (publication, personne) sur tous les enregistrements sources de la publication. Idempotent."""
        ...

    def detach_rejected_pair(self, publication_id: int, person_id: int) -> int:
        """Détache la personne rejetée de sa contribution à la publication, et retire ses épinglages sur les contributions sources de la publication. Renvoie le nombre de contributions détachées."""
        ...

    # ── Épinglage par l'administration ─────────────────────────────

    def pin_contributions(self, source_contribution_ids: list[int], person_id: int) -> None:
        """Épingle des contributions sources à une personne, et rattache leurs contributions à la personne. Le dernier épinglage d'une contribution source l'emporte."""
        ...

    # ── Périmètre, depuis les adresses ─────────────────────────────

    def find_source_contributions_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        """Renvoie les ids des contributions sources liées à l'une des adresses données."""
        ...
