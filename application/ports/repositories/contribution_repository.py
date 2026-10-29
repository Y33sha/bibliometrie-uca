"""Port ContributionRepository : accès aux contributions (`contributions`) et aux contributions sources (`source_contributions`).

Un seul port pour les deux : leurs opérations sont étroitement couplées.
"""

from datetime import datetime
from typing import Protocol, TypedDict


class ContributionRow(TypedDict):
    """Ligne rendue par `find_contributions` : clés d'une contribution."""

    id: int
    person_id: int | None
    publication_id: int


class AlignedSourceContributionRow(TypedDict):
    """Ligne rendue par `find_aligned_source_contributions` : contribution source d'une contribution, avec sa source et sa forme de nom."""

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
        """`publication_id` d'une contribution source, ou `None` si elle est absente ou rattachée à aucune publication."""
        ...

    # ── Contributions ─────────────

    def mark_contributions_for_name_form(self, person_id: int, name_form: str) -> int:
        """Marque pour la redécision de leur personne les contributions de la personne rattachées par le nom (`name`, `compatible_name`) dont une contribution source contient la forme de nom. Les contributions `manual` et celles d'un autre mode restent en l'état. Rend le nombre de contributions marquées."""
        ...

    def find_contributions(self, contribution_ids: list[int]) -> list[ContributionRow]:
        """Contributions demandées qui existent : identifiant, personne et publication."""
        ...

    def manual_contributions_of_person(
        self, person_id: int, publication_ids: list[int]
    ) -> dict[int, int]:
        """Contribution rattachée à la personne en mode `manual`, par publication donnée où elle en a une."""
        ...

    def find_aligned_source_contributions(
        self, contribution_ids: list[int]
    ) -> list[AlignedSourceContributionRow]:
        """Contributions sources des contributions données, avec leur source et leur forme de nom."""
        ...

    def reject_contribution(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) sur chaque enregistrement source de la publication (`rejected_contributions`) : le rejet suit les enregistrements sources quand la réconciliation regroupe autrement les publications. Idempotent."""
        ...

    def find_rejected_contribution(self, publication_id: int, person_id: int) -> datetime | None:
        """Date du premier rejet de la personne sur un enregistrement source de la publication, ou `None` sans rejet."""
        ...

    def delete_rejected_contribution(self, publication_id: int, person_id: int) -> None:
        """Lève le rejet d'une paire (publication, personne) sur tous les enregistrements sources de la publication. Idempotent."""
        ...

    def detach_rejected_pair(self, publication_id: int, person_id: int) -> int:
        """Retire la personne à sa contribution de cette publication, où elle est rejetée, et retire les épinglages des contributions sources de la publication à elle. Rend le nombre de contributions détachées."""
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
        """Ids des contributions sources liées à l'une des adresses données."""
        ...
