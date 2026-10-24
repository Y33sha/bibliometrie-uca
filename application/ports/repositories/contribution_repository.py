"""Port ContributionRepository — accès aux tables `contributions` et `source_contributions`.

Un seul port pour les deux : leurs opérations sont étroitement couplées.
"""

from datetime import datetime
from typing import Protocol, TypedDict


class ContributionPersonRow(TypedDict):
    """Ligne renvoyée par `get_contribution_person` : clés d'un groupe de `source_contribution_groups` rattaché à une personne."""

    id: int
    person_id: int
    publication_id: int


class AssignedSourceContributionRow(TypedDict):
    """Ligne renvoyée par `assign_orphan_source_contribution` : source et forme de nom de la contribution source rattachée."""

    source: str
    author_name_normalized: str | None


class ContributionRepository(Protocol):
    """Contrat d'accès aux tables contributions et source_contributions."""

    # ── source_contributions : lien personne ↔ contribution source ─────────────

    def assign_orphan_source_contribution(
        self,
        person_id: int,
        source_contribution_id: int,
    ) -> AssignedSourceContributionRow | None:
        """Pose `person_id` sur une contribution source orpheline. Retourne `{source, author_name_normalized}`, ou `None` si la contribution source est absente ou a déjà un `person_id` — `find_source_contribution_owner` départage."""
        ...

    def assign_orphan_source_contributions(
        self,
        person_id: int,
        source_contribution_ids: list[int],
    ) -> list[int]:
        """Pose `person_id` sur les contributions sources orphelines du lot et retourne leurs ids. Les contributions sources déjà rattachées restent intactes."""
        ...

    def find_source_contribution_owner(self, source_contribution_id: int) -> int | None:
        """`person_id` d'une contribution source. `None` si elle est orpheline ou absente."""
        ...

    def get_distinct_name_forms_from_source_contributions(
        self,
        source_contribution_ids: list[int],
    ) -> list[str]:
        """Les `author_name_normalized` distincts observés dans le lot de contributions sources."""
        ...

    def find_publication_id_for_source_contribution(
        self,
        source_contribution_id: int,
    ) -> int | None:
        """`publication_id` d'une contribution source, ou `None` si elle est absente ou rattachée à aucune publication."""
        ...

    def find_publication_ids_for_source_contributions(
        self,
        source_contribution_ids: list[int],
    ) -> list[int]:
        """Les `publication_id` distincts couverts par un lot de contributions sources. Sert au pré-contrôle de rejet en batch."""
        ...

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        """Détache (person_id → NULL) les contributions sources d'une personne sous une forme de nom donnée, sauf celles que l'admin a épinglées sur elle. Retourne le nombre de contributions sources détachées."""
        ...

    def detach_groups_for_name_form(self, person_id: int, name_form: str) -> list[int]:
        """Retire la personne (et le mode de résolution) de ses groupes de contributions sources rattachés par le nom (`name`, `compatible_name`) dont un membre porte la forme de nom. Les groupes `manual` et ceux d'un autre mode restent rattachés. Retourne les `publication_id` distincts des groupes détachés."""
        ...

    # ── contributions ────────────────────────────────────────────────

    def get_contribution_person(self, contribution_id: int) -> ContributionPersonRow | None:
        """Le groupe (`id`, `person_id`, `publication_id`) de `source_contribution_groups`, ou `None` si l'id n'existe pas ou si le groupe n'a pas de personne."""
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

    def delete_orphan_contributions_for_person(self, person_id: int) -> int:
        """Supprime les lignes consolidées de la personne dépourvues de toute contribution source active. Retourne le nombre supprimé."""
        ...

    # ── confirmed_source_contributions (épinglage admin, must-link au grain de la contribution source) ──

    def pin_contributions(self, source_contribution_ids: list[int], person_id: int) -> None:
        """Épingle des contributions sources à une personne dans `confirmed_source_contributions` (résolution admin d'orphelines), et rattache leurs groupes à la personne (`pinned_groups_sql`). Upsert par contribution source : le dernier épinglage l'emporte."""
        ...

    # ── Propagation UCA depuis les adresses ────────────────────────

    def find_source_contributions_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        """Ids des contributions sources liées à l'une des adresses données (via `source_contribution_addresses`)."""
        ...

    # ── Recomposition d'une contribution depuis ses contributions sources ───────

    def consolidate_contributions(self, person_id: int, publication_ids: list[int]) -> None:
        """Crée et recompose les lignes consolidées de la personne sur ces publications, depuis ses contributions sources, par les requêtes de la phase `contributions`."""
        ...
