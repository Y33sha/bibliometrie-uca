"""Attribuer à une personne des contributions orphelines : groupes de contributions sources du périmètre rattachés à aucune personne.

Ces opérations (unitaire et par lot) sont exposées par l'API admin (`POST /api/contributions/orphans/...`) — actions utilisateur, hors pipeline. Elles épinglent les membres de chaque groupe à la personne, ce qui rattache le groupe.

Elles vérifient l'existence de la personne cible : elles écrivent des lignes qui la référencent, et sans cette garde une cible absente se traduirait en violation de clé étrangère.
"""

import logging

from application.audit_log import emit_event
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.contribution_repository import (
    ContributionRepository,
    GroupRow,
)
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import (
    ContributionAlreadyAssignedError,
    NotFoundError,
    PersonAlreadyInPublicationError,
    RejectedPairError,
)

logger = logging.getLogger(__name__)


def _require_person(person_id: int, *, repo: PersonRepository) -> None:
    """Refuse une personne cible absente, que les écritures suivantes référencent."""
    if repo.find_by_id(person_id) is None:
        raise NotFoundError(f"Personne {person_id} introuvable")


def _resolve_rejection(
    person_id: int,
    publication_ids: list[int],
    *,
    contribution_repo: ContributionRepository,
    force: bool,
) -> None:
    """Pré-contrôle des paires rejetées avant une réassignation.

    Cherche, parmi les `publication_ids`, celles dont la paire avec `person_id` est rejetée. Si au moins une l'est :
    - sans `force` : lève `RejectedPairError` (→ 409), qui liste les paires et leur date de rejet, pour que l'UI demande confirmation ;
    - avec `force` : lève le rejet de chaque paire, ce qui laisse la réassignation recréer le lien.
    """
    rejected = [
        (publication_id, at)
        for publication_id in publication_ids
        if (at := contribution_repo.find_rejected_contribution(publication_id, person_id))
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
        contribution_repo.delete_rejected_contribution(publication_id, person_id)
    # La levée procède d'une confirmation unique : un événement, qui liste les publications dont
    # le rejet tombe, plutôt qu'un par paire.
    emit_event(
        "contribution.unrejected",
        "person",
        person_id,
        {"publication_ids": [publication_id for publication_id, _ in rejected]},
    )


def _attach_groups(
    person_id: int,
    groups: list[GroupRow],
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
) -> None:
    """Rattache les groupes à la personne : épingle tous leurs membres, ce qui rattache les groupes (`pin_contributions`), ajoute leurs formes de nom sous leur source, puis recalcule l'appartenance au périmètre de leurs publications."""
    members = contribution_repo.find_group_members([g["id"] for g in groups])
    member_ids = [m["source_contribution_id"] for m in members]
    # Épingler la résolution admin (must-link au grain de la contribution source) : le pipeline la
    # relit comme entrée fixe et ne re-dérive jamais ces contributions sources.
    contribution_repo.pin_contributions(member_ids, person_id)
    for name_form, source in sorted(
        {(m["author_name_normalized"], m["source"]) for m in members if m["author_name_normalized"]}
    ):
        repo.add_name_form(person_id, name_form, source=source)
    perimeter_recompute.refresh_publications(sorted({g["publication_id"] for g in groups}))


def assign_orphan_contribution(
    person_id: int,
    contribution_id: int,
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    force: bool = False,
) -> None:
    """Attribue une contribution orpheline, le groupe `contribution_id` sans personne, à une personne.

    1. Pré-contrôle de rejet : si la paire (publication, personne) est rejetée et que `force` est faux, lève `RejectedPairError` ; avec `force`, lève le rejet d'abord (cf. `_resolve_rejection`)
    2. Rattache le groupe à la personne (`_attach_groups`)

    Lève `NotFoundError` si la personne ou le groupe est absent, `ContributionAlreadyAssignedError` si le groupe est déjà rattaché à une personne, `PersonAlreadyInPublicationError` si la personne a déjà un groupe manuel dans la publication.
    """
    _require_person(person_id, repo=repo)

    group = next(iter(contribution_repo.find_groups([contribution_id])), None)
    if group is None:
        raise NotFoundError(f"Contribution #{contribution_id} introuvable")
    if group["person_id"] is not None:
        raise ContributionAlreadyAssignedError(contribution_id, group["person_id"])
    manual = contribution_repo.manual_groups_of_person(person_id, [group["publication_id"]])
    if group["publication_id"] in manual:
        raise PersonAlreadyInPublicationError(
            group["publication_id"], manual[group["publication_id"]]
        )

    _resolve_rejection(
        person_id,
        [group["publication_id"]],
        contribution_repo=contribution_repo,
        force=force,
    )
    _attach_groups(
        person_id,
        [group],
        repo=repo,
        contribution_repo=contribution_repo,
        perimeter_recompute=perimeter_recompute,
    )

    emit_event(
        "contribution.assigned",
        "person",
        person_id,
        {"contribution_id": contribution_id, "publication_id": group["publication_id"]},
    )


def assign_orphan_contribution_to_new_person(
    contribution_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    force: bool = False,
) -> int:
    """Crée une personne (`PersonRepository.create`), puis lui attribue la contribution orpheline `contribution_id` (`assign_orphan_contribution`). Retourne l'id de la personne créée.

    Lève `ValidationError` sans patronyme, et les erreurs d'`assign_orphan_contribution`.
    """
    person_id = repo.create(last_name, first_name)
    assign_orphan_contribution(
        person_id,
        contribution_id,
        repo=repo,
        contribution_repo=contribution_repo,
        perimeter_recompute=perimeter_recompute,
        force=force,
    )
    return person_id


def batch_assign_orphan_contributions(
    person_id: int,
    group_ids: list[int],
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    force: bool = False,
) -> int:
    """Attribue en lot plusieurs contributions orphelines, groupes sans personne, à une personne.

    Un groupe absent, déjà rattaché, ou d'une publication où la personne a déjà un groupe manuel est une anomalie : il est écarté du lot et journalisé, le reste du lot est rattaché (`_attach_groups`). Pré-contrôle de rejet sur l'ensemble des publications du lot (cf. `_resolve_rejection`) : sans `force`, une seule paire rejetée bloque tout le lot (`RejectedPairError`) ; avec `force`, les rejets sont d'abord levés.

    Retourne le nombre de groupes rattachés. Lève `NotFoundError` si la personne n'existe pas.
    """
    if not group_ids:
        return 0

    _require_person(person_id, repo=repo)

    orphans = [g for g in contribution_repo.find_groups(group_ids) if g["person_id"] is None]
    manual = contribution_repo.manual_groups_of_person(
        person_id, sorted({g["publication_id"] for g in orphans})
    )
    groups = [g for g in orphans if g["publication_id"] not in manual]
    skipped = sorted(set(group_ids) - {g["id"] for g in groups})
    if skipped:
        logger.warning(
            "Rattachement à la personne %d : contributions absentes, déjà rattachées, ou dans une publication où la personne a déjà une contribution manuelle, écartées : %s",
            person_id,
            skipped,
        )
    if groups:
        _resolve_rejection(
            person_id,
            sorted({g["publication_id"] for g in groups}),
            contribution_repo=contribution_repo,
            force=force,
        )
        _attach_groups(
            person_id,
            groups,
            repo=repo,
            contribution_repo=contribution_repo,
            perimeter_recompute=perimeter_recompute,
        )

    emit_event(
        "contribution.batch_assigned",
        "person",
        person_id,
        {"group_ids": [g["id"] for g in groups], "skipped": skipped},
    )
    return len(groups)
