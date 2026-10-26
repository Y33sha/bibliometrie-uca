"""Service Contributions — écritures sur l'agrégat Contribution.

Couvre les contributions (`contributions`) et les contributions sources (`source_contributions`) : rejet d'une contribution, et attribution à une personne des contributions orphelines, contributions du périmètre rattachées à aucune personne.

La construction du stock relève du pipeline, qui écrit en SQL ensembliste : les phases `normalize`, `affiliations`, `countries` et `persons` alimentent les contributions sources, la phase `author_grouping` forme les contributions et la phase `persons` les rattache aux personnes.
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
    """Rejette durablement une paire (publication, personne) : enregistre que cette personne n'est pas l'auteur de cette publication.

    Opération unique partagée par les deux façons de rejeter une contribution (depuis la fiche personne et depuis la fiche publication). Trois effets :

    1. Enregistre la paire dans `rejected_contributions`. Ce registre est consulté par le matching des personnes, qui écarte toute paire rejetée : le rejet survit aux exécutions suivantes du pipeline.
    2. Retire la personne à sa contribution dans la publication, et retire les épinglages des contributions sources de la publication à elle (`detach_rejected_pair`).
    3. Recalcule l'appartenance au périmètre de la publication.

    Retourne le nombre de contributions détachées.
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
    """Écritures sur les contributions : rejet, et attribution des contributions orphelines.

    L'attribution vérifie l'existence de la personne cible : elle écrit des lignes qui la référencent, et sans cette garde une cible absente se traduirait en violation de clé étrangère.
    """

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

        Retrouve la paire (publication, personne) à partir de la contribution `contribution_id` puis applique `reject_pair`. Supprime ensuite les formes de nom de la personne qu'aucune source restante n'atteste.

        Lève NotFoundError si la contribution n'existe pas ou n'a pas de personne.
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
        """Attribue une contribution orpheline, la contribution `contribution_id` sans personne, à une personne.

        1. Pré-contrôle de rejet : si la paire (publication, personne) est rejetée et que `force` est faux, lève `RejectedPairError` ; avec `force`, lève le rejet d'abord (cf. `_resolve_rejection`)
        2. Rattache la contribution à la personne (`_attach_contributions`)

        Lève `NotFoundError` si la personne ou la contribution est absente, `ContributionAlreadyAssignedError` si la contribution est déjà rattachée à une personne, `PersonAlreadyInPublicationError` si la personne a déjà une contribution manuelle dans la publication.
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
        """Crée une personne (`PersonRepository.create`), puis lui attribue la contribution orpheline `contribution_id` (`assign_orphan_contribution`). Retourne l'id de la personne créée.

        Lève `ValidationError` sans patronyme, et les erreurs d'`assign_orphan_contribution`.
        """
        person_id = self._persons.create(last_name, first_name)
        self.assign_orphan_contribution(person_id, contribution_id, force=force)
        return person_id

    def batch_assign_orphan_contributions(
        self, person_id: int, contribution_ids: list[int], *, force: bool = False
    ) -> int:
        """Attribue en lot plusieurs contributions orphelines, contributions sans personne, à une personne.

        Une contribution absente, déjà rattachée, ou d'une publication où la personne a déjà une contribution manuelle est une anomalie : elle est écartée du lot et journalisée, le reste du lot est rattaché (`_attach_contributions`). Pré-contrôle de rejet sur l'ensemble des publications du lot (cf. `_resolve_rejection`) : sans `force`, une seule paire rejetée bloque tout le lot (`RejectedPairError`) ; avec `force`, les rejets sont d'abord levés.

        Retourne le nombre de contributions rattachées. Lève `NotFoundError` si la personne n'existe pas.
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
        """Refuse une personne cible absente, que les écritures suivantes référencent."""
        if self._persons.find_by_id(person_id) is None:
            raise NotFoundError(f"Personne {person_id} introuvable")

    def _resolve_rejection(
        self, person_id: int, publication_ids: list[int], *, force: bool
    ) -> None:
        """Pré-contrôle des paires rejetées avant une réassignation.

        Cherche, parmi les `publication_ids`, celles dont la paire avec `person_id` est rejetée. Si au moins une l'est :
        - sans `force` : lève `RejectedPairError` (→ 409), qui liste les paires et leur date de rejet, pour que l'UI demande confirmation ;
        - avec `force` : lève le rejet de chaque paire, ce qui laisse la réassignation recréer le lien.
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
        # La levée procède d'une confirmation unique : un événement, qui liste les publications dont
        # le rejet tombe, plutôt qu'un par paire.
        emit_event(
            "contribution.unrejected",
            "person",
            person_id,
            {"publication_ids": [publication_id for publication_id, _ in rejected]},
        )

    def _attach_contributions(self, person_id: int, contributions: list[ContributionRow]) -> None:
        """Rattache les contributions à la personne : épingle toutes leurs contributions sources, ce qui rattache les contributions (`pin_contributions`), ajoute leurs formes de nom sous leur source, puis recalcule l'appartenance au périmètre de leurs publications."""
        members = self._contributions.find_aligned_source_contributions(
            [g["id"] for g in contributions]
        )
        member_ids = [m["source_contribution_id"] for m in members]
        # Épingler la résolution admin (must-link au grain de la contribution source) : le pipeline la
        # relit comme entrée fixe et ne re-dérive jamais ces contributions sources.
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
