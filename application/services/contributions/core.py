"""Service Contributions — écritures sur l'agrégat Contribution.

Couvre les contributions (`contributions`) et les contributions sources (`source_contributions`). Les opérations servent des actions utilisateur : rejeter une contribution, propager un changement de périmètre. Elles traitent une paire ou une contribution source à la fois.

La construction du stock relève du pipeline, qui écrit en SQL ensembliste : les phases `normalize`, `affiliations`, `countries` et `persons` alimentent les contributions sources, la phase `author_grouping` forme les groupes et la phase `persons` les rattache aux personnes.
"""

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.pipeline.source_contribution_perimeter import (
    SourceContributionPerimeterRecompute,
)
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import NotFoundError


def reject_pair(
    publication_id: int,
    person_id: int,
    *,
    conn: Connection,
    repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
) -> int:
    """Rejette durablement une paire (publication, personne) : enregistre que cette personne n'est pas l'auteur de cette publication.

    Opération unique partagée par les deux façons de rejeter une contribution (depuis la fiche personne et depuis la fiche publication). Trois effets :

    1. Enregistre la paire dans `rejected_contributions`. Ce registre est consulté par le matching des personnes, qui écarte toute paire rejetée : le rejet survit aux exécutions suivantes du pipeline.
    2. Retire la personne à son groupe dans la publication, et retire les épinglages des contributions sources de la publication à elle (`detach_rejected_pair`).
    3. Recalcule l'appartenance au périmètre de la publication.

    Retourne le nombre de groupes détachés.
    """
    repo.reject_contribution(publication_id, person_id)
    detached = repo.detach_rejected_pair(publication_id, person_id)
    perimeter_recompute.refresh_publications(conn, [publication_id])

    emit_event(
        "contribution.rejected",
        "publication",
        publication_id,
        {"person_id": person_id},
    )
    return detached


def exclude_contribution(
    contribution_id: int,
    *,
    conn: Connection,
    repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    person_repo: PersonRepository,
) -> None:
    """Rejette une contribution désignée par son identifiant.

    Retrouve la paire (publication, personne) à partir du groupe `contribution_id` puis applique `reject_pair`. Supprime ensuite les formes de nom de la personne qu'aucune source restante n'atteste.

    Lève NotFoundError si le groupe n'existe pas ou n'a pas de personne.
    """
    group = next(iter(repo.find_groups([contribution_id])), None)
    person_id = group["person_id"] if group else None
    if group is None or person_id is None:
        raise NotFoundError(f"Contribution {contribution_id} introuvable")

    reject_pair(
        group["publication_id"],
        person_id,
        conn=conn,
        repo=repo,
        perimeter_recompute=perimeter_recompute,
    )
    person_repo.delete_orphan_name_forms_for_person(person_id)


def propagate_in_perimeter_for_addresses(
    conn: Connection,
    address_ids: list[int],
    *,
    repo: ContributionRepository,
    perimeter_structures: PerimeterStructures,
    perimeter_recompute: SourceContributionPerimeterRecompute,
) -> None:
    """Recalcule le périmètre des contributions sources liées aux adresses données, de leurs groupes et de leurs publications.

    Appelé en tâche de fond après chaque review/assign/unassign d'adresse.
    """
    if not address_ids:
        return

    perimeter_ids = perimeter_structures.persons_structure_ids(conn)
    if not perimeter_ids:
        return

    affected_source_contribution_ids = repo.find_source_contributions_by_addresses(address_ids)
    if not affected_source_contribution_ids:
        return

    perimeter_recompute.recompute_perimeter(conn, affected_source_contribution_ids, perimeter_ids)
