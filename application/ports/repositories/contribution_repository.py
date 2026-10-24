"""Port ContributionRepository — accès aux contributions (groupes de `source_contribution_groups`) et aux `source_contributions`.

Un seul port pour les deux : leurs opérations sont étroitement couplées.
"""

from datetime import datetime
from typing import Protocol, TypedDict


class GroupRow(TypedDict):
    """Ligne renvoyée par `find_groups` : clés d'un groupe de `source_contribution_groups`."""

    id: int
    person_id: int | None
    publication_id: int


class GroupMemberRow(TypedDict):
    """Ligne renvoyée par `find_group_members` : membre d'un groupe, avec sa source et sa forme de nom."""

    source_contribution_id: int
    source: str
    author_name_normalized: str | None


class ContributionRepository(Protocol):
    """Contrat d'accès aux contributions et aux contributions sources."""

    # ── source_contributions : lien personne ↔ contribution source ─────────────

    def assign_orphan_source_contributions(
        self,
        person_id: int,
        source_contribution_ids: list[int],
    ) -> list[int]:
        """Pose `person_id` sur les contributions sources orphelines du lot et retourne leurs ids. Les contributions sources déjà rattachées restent intactes."""
        ...

    def find_publication_id_for_source_contribution(
        self,
        source_contribution_id: int,
    ) -> int | None:
        """`publication_id` d'une contribution source, ou `None` si elle est absente ou rattachée à aucune publication."""
        ...

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        """Détache (person_id → NULL) les contributions sources d'une personne sous une forme de nom donnée, sauf celles que l'admin a épinglées sur elle. Retourne le nombre de contributions sources détachées."""
        ...

    def detach_groups_for_name_form(self, person_id: int, name_form: str) -> list[int]:
        """Retire la personne (et le mode de résolution) de ses groupes de contributions sources rattachés par le nom (`name`, `compatible_name`) dont un membre porte la forme de nom. Les groupes `manual` et ceux d'un autre mode restent rattachés. Retourne les `publication_id` distincts des groupes détachés."""
        ...

    # ── Contributions : groupes de contributions sources ─────────────

    def find_groups(self, group_ids: list[int]) -> list[GroupRow]:
        """Les groupes (`id`, `person_id`, `publication_id`) de `source_contribution_groups` parmi `group_ids`. Les ids absents sont omis."""
        ...

    def manual_groups_of_person(self, person_id: int, publication_ids: list[int]) -> dict[int, int]:
        """Groupe rattaché à la personne en mode `manual`, par publication de `publication_ids` où elle en a un."""
        ...

    def find_group_members(self, group_ids: list[int]) -> list[GroupMemberRow]:
        """Les membres des groupes `group_ids`, avec leur source et leur forme de nom."""
        ...

    def reject_contribution(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) sur chaque enregistrement source de la publication (`rejected_contributions`) : le rejet suit les enregistrements sources quand la réconciliation regroupe autrement les publications. Idempotent."""
        ...

    def find_rejected_contribution(self, publication_id: int, person_id: int) -> datetime | None:
        """Date du premier rejet de la personne sur un enregistrement source de la publication, ou None si la publication n'est pas rejetée pour elle."""
        ...

    def delete_rejected_contribution(self, publication_id: int, person_id: int) -> None:
        """Lève le rejet d'une paire (publication, personne) sur tous les enregistrements sources de la publication. Idempotent."""
        ...

    def detach_rejected_pair(self, publication_id: int, person_id: int) -> int:
        """Détache toutes les contributions sources et le groupe de la personne sur cette publication, où elle est rejetée, et retire leurs épinglages. Retourne le nombre de contributions sources détachées."""
        ...

    # ── confirmed_source_contributions (épinglage admin, must-link au grain de la contribution source) ──

    def pin_contributions(self, source_contribution_ids: list[int], person_id: int) -> None:
        """Épingle des contributions sources à une personne dans `confirmed_source_contributions`, et rattache leurs groupes à la personne (`pinned_groups_sql`). Upsert par contribution source : le dernier épinglage l'emporte."""
        ...

    # ── Propagation UCA depuis les adresses ────────────────────────

    def find_source_contributions_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        """Ids des contributions sources liées à l'une des adresses données (via `source_contribution_addresses`)."""
        ...
