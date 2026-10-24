"""Attribuer à une personne des contributions sources orphelines.

Ces deux opérations (unitaire et par lot) sont exposées par l'API admin (`POST /api/contributions/orphans/...`) — actions utilisateur, hors pipeline. À l'interface entre `persons`, `source_contributions` et `publications`, leur issue est la création ou la mise à jour de lignes dans `contributions`.

Les lignes de `contributions` se recomposent depuis les contributions sources par les requêtes de la phase `contributions`, restreintes à la personne et aux publications concernées.

Les deux opérations vérifient l'existence de la personne cible : elles écrivent des lignes qui la référencent, et sans cette garde une cible absente se traduirait en violation de clé étrangère.
"""

import logging

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import (
    ContributionAlreadyAssignedError,
    NotFoundError,
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
    audit_repo: AuditRepository | None,
    force: bool,
) -> None:
    """Pré-contrôle des paires rejetées avant une réassignation.

    Cherche, parmi les `publication_ids`, celles dont la paire avec
    `person_id` figure dans `rejected_contributions`. Si au moins une est
    rejetée :
    - sans `force` : lève `RejectedPairError` (→ 409) listant les paires et
      leur date de rejet, pour que l'UI demande confirmation ;
    - avec `force` : lève le rejet de chaque paire (suppression du registre +
      événement d'audit), ce qui laisse la réassignation recréer le lien.
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
    # La levée procède d'une confirmation unique : un événement, portant les publications dont
    # le rejet tombe, plutôt qu'un par paire.
    emit_event(
        audit_repo,
        "contribution.unrejected",
        "person",
        person_id,
        {"publication_ids": [publication_id for publication_id, _ in rejected]},
    )


def assign_orphan_contribution(
    person_id: int,
    source_contribution_id: int,
    *,
    conn: Connection,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
    force: bool = False,
) -> None:
    """Attribue une contribution source orpheline (`person_id IS NULL`) à une personne.

    1. Pré-contrôle de rejet : si la paire (publication, personne) est rejetée
       et que `force` est faux, lève `RejectedPairError` ; avec `force`, lève
       le rejet d'abord (cf. `_resolve_rejection`)
    2. Pose `person_id` sur la contribution source, si elle est orpheline
    3. Ajoute la forme de nom, sous la source de la contribution source
    4. Crée/met à jour la contribution canonique + FK source
    5. Recalcule l'appartenance au périmètre de la publication

    Lève `NotFoundError` si la personne ou la contribution source est absente, `ContributionAlreadyAssignedError` si elle est déjà rattachée à une personne.
    """
    _require_person(person_id, repo=repo)

    publication_id = contribution_repo.find_publication_id_for_source_contribution(
        source_contribution_id
    )
    if publication_id is not None:
        _resolve_rejection(
            person_id,
            [publication_id],
            contribution_repo=contribution_repo,
            audit_repo=audit_repo,
            force=force,
        )

    row = contribution_repo.assign_orphan_source_contribution(person_id, source_contribution_id)
    if row is None:
        # L'UPDATE pose `person_id` sur une contribution source orpheline seulement : son échec signale
        # une contribution source absente ou déjà rattachée. Un `owner` nul tranche pour l'absence —
        # sur une contribution source orpheline et existante, l'UPDATE aboutit.
        owner = contribution_repo.find_source_contribution_owner(source_contribution_id)
        if owner is None:
            raise NotFoundError(f"Contribution source #{source_contribution_id} introuvable")
        raise ContributionAlreadyAssignedError(source_contribution_id, owner)

    # Épingler la résolution admin (must-link au grain de la contribution source) : le pipeline la
    # relit comme entrée fixe et ne re-dérive jamais cette contribution source.
    contribution_repo.pin_contributions([source_contribution_id], person_id)

    # Ajouter la forme de nom
    if row["author_name_normalized"]:
        repo.add_name_form(person_id, row["author_name_normalized"], source=row["source"])

    if publication_id is not None:
        contribution_repo.consolidate_contributions(person_id, [publication_id])
        perimeter_recompute.refresh_publications(conn, [publication_id])
    # `group_structures` (agrégation des structure_ids) maintenue uniquement
    # par le pipeline — pas de refresh sur action admin (staleness bornée à un run).

    emit_event(
        audit_repo,
        "contribution.assigned",
        "person",
        person_id,
        {"source_contribution_id": source_contribution_id, "publication_id": publication_id},
    )


def batch_assign_orphan_contributions(
    person_id: int,
    source_contribution_ids: list[int],
    *,
    conn: Connection,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
    force: bool = False,
) -> int:
    """Attribue en batch plusieurs contributions sources orphelines à une personne.

    Pré-contrôle de rejet sur l'ensemble des publications couvertes (cf.
    `_resolve_rejection`) : sans `force`, une seule paire rejetée bloque tout
    le lot (`RejectedPairError`) ; avec `force`, les rejets sont d'abord levés.

    Une contribution source absente ou déjà rattachée est une anomalie : elle est écartée du lot et journalisée, le reste du lot est rattaché. L'appartenance au périmètre des publications du lot est recalculée.

    Retourne le nombre de contributions sources rattachées. Lève `NotFoundError` si la personne n'existe pas.
    """
    if not source_contribution_ids:
        return 0

    _require_person(person_id, repo=repo)

    publication_ids = contribution_repo.find_publication_ids_for_source_contributions(
        source_contribution_ids
    )
    _resolve_rejection(
        person_id,
        publication_ids,
        contribution_repo=contribution_repo,
        audit_repo=audit_repo,
        force=force,
    )

    assigned = contribution_repo.assign_orphan_source_contributions(
        person_id, source_contribution_ids
    )
    skipped = sorted(set(source_contribution_ids) - set(assigned))
    if skipped:
        logger.warning(
            "Rattachement à la personne %d : contributions sources absentes ou déjà rattachées, écartées : %s",
            person_id,
            skipped,
        )
    if assigned:
        contribution_repo.pin_contributions(assigned, person_id)
        contribution_repo.consolidate_contributions(person_id, publication_ids)
        perimeter_recompute.refresh_publications(conn, publication_ids)
        for name_form in contribution_repo.get_distinct_name_forms_from_source_contributions(
            assigned
        ):
            repo.add_name_form(person_id, name_form)

    # `group_structures` (agrégation des structure_ids) maintenue uniquement
    # par le pipeline — pas de refresh sur action admin (staleness bornée à un run).

    emit_event(
        audit_repo,
        "contribution.batch_assigned",
        "person",
        person_id,
        {"source_contribution_ids": assigned, "skipped": skipped},
    )
    return len(assigned)
