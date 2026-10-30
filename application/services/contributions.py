"""Service des contributions : écritures sur les contributions (`contributions`) et les contributions sources (`source_contributions`).

Opérations : rejet d'une contribution, et attribution à une personne des contributions orphelines, contributions du périmètre sans personne.

Le pipeline construit le stock en SQL ensembliste. Les phases `normalize`, `affiliations`, `countries` et `persons` alimentent les contributions sources. La phase `author_grouping` forme les contributions, et la phase `persons` les rattache aux personnes.
"""

import logging

from application.audit_log import emit_event
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.contribution_repository import (
    ContributionRepository,
    ContributionRow,
)
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import (
    ContributionAlreadyAssignedError,
    NotFoundError,
    PersonAlreadyInPublicationError,
    RejectedPairError,
)

logger = logging.getLogger(__name__)


def reject_pair(
    publication_id: int,
    person_id: int,
    *,
    repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
) -> int:
    """Rejette durablement une paire (publication, personne) : la personne n'est pas l'auteur de la publication.

    Le rejet depuis la fiche d'une personne et le rejet depuis la fiche d'une publication passent par cette fonction. Effets :

    1. La paire s'inscrit dans `rejected_contributions`. Le rattachement des personnes écarte ces paires, donc le rejet survit aux exécutions suivantes.
    2. La personne est détachée de sa contribution à la publication, et ses épinglages sur les contributions sources de la publication sont retirés (`detach_rejected_pair`).
    3. L'appartenance de la publication au périmètre est recalculée.

    Renvoie le nombre de contributions détachées.
    """
    repo.reject_contribution(publication_id, person_id)
    detached = repo.detach_rejected_pair(publication_id, person_id)
    perimeter_recompute.refresh_publications([publication_id])

    emit_event(
        "contribution.rejected",
        "publication",
        publication_id,
        {"person_id": person_id},
    )
    return detached


class ContributionService:
    """Écritures sur les contributions : rejet, et attribution des contributions orphelines."""

    def __init__(
        self,
        *,
        persons: PersonRepository,
        contributions: ContributionRepository,
        perimeter_recompute: PublicationPerimeterRecompute,
    ) -> None:
        self._persons = persons
        self._contributions = contributions
        self._perimeter_recompute = perimeter_recompute

    # ── Rejet ──

    def exclude_contribution(self, contribution_id: int) -> None:
        """Rejette une contribution désignée par son identifiant.

        Applique `reject_pair` à la paire (publication, personne) de la contribution. Supprime ensuite les formes de nom de la personne absentes de ses contributions sources restantes.

        Raises:
            NotFoundError: contribution absente ou sans personne.
        """
        contribution = next(iter(self._contributions.find_contributions([contribution_id])), None)
        person_id = contribution["person_id"] if contribution else None
        if contribution is None or person_id is None:
            raise NotFoundError(f"Contribution {contribution_id} introuvable")

        reject_pair(
            contribution["publication_id"],
            person_id,
            repo=self._contributions,
            perimeter_recompute=self._perimeter_recompute,
        )
        self._persons.delete_orphan_name_forms_for_person(person_id)

    # ── Contributions orphelines ──

    def assign_orphan_contribution(
        self, person_id: int, contribution_id: int, *, force: bool = False
    ) -> None:
        """Attribue une contribution orpheline (sans personne) à une personne.

        Si la paire (publication, personne) est rejetée, `force` retire d'abord le rejet (`_resolve_rejection`). La contribution est ensuite rattachée à la personne (`_attach_contributions`).

        Raises:
            RejectedPairError: paire rejetée, sans `force`.
            NotFoundError: personne ou contribution absente.
            ContributionAlreadyAssignedError: contribution déjà rattachée à une personne.
            PersonAlreadyInPublicationError: la personne a déjà une contribution manuelle dans la publication.
        """
        self._require_person(person_id)

        contribution = next(iter(self._contributions.find_contributions([contribution_id])), None)
        if contribution is None:
            raise NotFoundError(f"Contribution #{contribution_id} introuvable")
        if contribution["person_id"] is not None:
            raise ContributionAlreadyAssignedError(contribution_id, contribution["person_id"])
        manual = self._contributions.manual_contributions_of_person(
            person_id, [contribution["publication_id"]]
        )
        if contribution["publication_id"] in manual:
            raise PersonAlreadyInPublicationError(
                contribution["publication_id"], manual[contribution["publication_id"]]
            )

        self._resolve_rejection(person_id, [contribution["publication_id"]], force=force)
        self._attach_contributions(person_id, [contribution])

        emit_event(
            "contribution.assigned",
            "person",
            person_id,
            {"contribution_id": contribution_id, "publication_id": contribution["publication_id"]},
        )

    def assign_orphan_contribution_to_new_person(
        self, contribution_id: int, last_name: str, first_name: str, *, force: bool = False
    ) -> int:
        """Crée une personne (`PersonRepository.create`), puis lui attribue la contribution orpheline (`assign_orphan_contribution`). Renvoie l'id de la personne créée.

        Lève aussi les erreurs d'`assign_orphan_contribution`.

        Raises:
            ValidationError: nom de famille vide.
        """
        person_id = self._persons.create(last_name, first_name)
        self.assign_orphan_contribution(person_id, contribution_id, force=force)
        return person_id

    def batch_assign_orphan_contributions(
        self, person_id: int, contribution_ids: list[int], *, force: bool = False
    ) -> int:
        """Attribue en lot des contributions orphelines à une personne. Renvoie le nombre de contributions rattachées.

        Une contribution absente, déjà rattachée, ou dans une publication où la personne a déjà une contribution manuelle est écartée du lot et journalisée. Le reste du lot est rattaché (`_attach_contributions`).

        Les rejets se contrôlent sur toutes les publications du lot (`_resolve_rejection`). Sans `force`, une seule paire rejetée bloque le lot. Avec `force`, les rejets sont d'abord retirés.

        Raises:
            NotFoundError: personne introuvable.
            RejectedPairError: paire rejetée, sans `force`.
        """
        if not contribution_ids:
            return 0

        self._require_person(person_id)

        orphans = [
            g
            for g in self._contributions.find_contributions(contribution_ids)
            if g["person_id"] is None
        ]
        manual = self._contributions.manual_contributions_of_person(
            person_id, sorted({g["publication_id"] for g in orphans})
        )
        contributions = [g for g in orphans if g["publication_id"] not in manual]
        skipped = sorted(set(contribution_ids) - {g["id"] for g in contributions})
        if skipped:
            logger.warning(
                "Rattachement à la personne %d : contributions absentes, déjà rattachées, ou dans une publication où la personne a déjà une contribution manuelle, écartées : %s",
                person_id,
                skipped,
            )
        if contributions:
            self._resolve_rejection(
                person_id, sorted({g["publication_id"] for g in contributions}), force=force
            )
            self._attach_contributions(person_id, contributions)

        emit_event(
            "contribution.batch_assigned",
            "person",
            person_id,
            {"contribution_ids": [g["id"] for g in contributions], "skipped": skipped},
        )
        return len(contributions)

    def _require_person(self, person_id: int) -> None:
        """Refuse une personne cible absente (`NotFoundError`)."""
        if self._persons.find_by_id(person_id) is None:
            raise NotFoundError(f"Personne {person_id} introuvable")

    def _resolve_rejection(
        self, person_id: int, publication_ids: list[int], *, force: bool
    ) -> None:
        """Contrôle les paires rejetées avant une réattribution de la personne aux publications.

        Sans `force`, une paire rejetée lève `RejectedPairError` (409), avec les paires et leur date de rejet. L'interface demande alors confirmation. Avec `force`, le rejet de chaque paire est retiré, et la réattribution recrée le lien.
        """
        rejected = [
            (publication_id, at)
            for publication_id in publication_ids
            if (at := self._contributions.find_rejected_contribution(publication_id, person_id))
            is not None
        ]
        if not rejected:
            return
        if not force:
            raise RejectedPairError(
                [
                    {
                        "publication_id": publication_id,
                        "person_id": person_id,
                        "rejected_at": at.isoformat(),
                    }
                    for publication_id, at in rejected
                ]
            )
        for publication_id, _ in rejected:
            self._contributions.delete_rejected_contribution(publication_id, person_id)
        # Une confirmation unique donne un seul événement, avec les publications à rejet retiré.
        emit_event(
            "contribution.unrejected",
            "person",
            person_id,
            {"publication_ids": [publication_id for publication_id, _ in rejected]},
        )

    def _attach_contributions(self, person_id: int, contributions: list[ContributionRow]) -> None:
        """Rattache les contributions à la personne par l'épinglage de leurs contributions sources (`pin_contributions`). Ajoute ensuite leurs formes de nom avec leur source, puis recalcule l'appartenance au périmètre de leurs publications."""
        members = self._contributions.find_aligned_source_contributions(
            [g["id"] for g in contributions]
        )
        member_ids = [m["source_contribution_id"] for m in members]
        # La décision de l'administration est épinglée sur chaque contribution source. Le pipeline la relit comme une donnée fixe.
        self._contributions.pin_contributions(member_ids, person_id)
        for name_form, source in sorted(
            {
                (m["author_name_normalized"], m["source"])
                for m in members
                if m["author_name_normalized"]
            }
        ):
            self._persons.add_name_form(person_id, name_form, source=source)
        self._perimeter_recompute.refresh_publications(
            sorted({g["publication_id"] for g in contributions})
        )
