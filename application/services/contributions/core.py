"""Service Contributions — écritures sur l'agrégat Contribution, transaction-agnostiques.

Couvre les contributions (`contributions`) et les contributions sources (`source_contributions`), dont le `person_id` fait le lien vers la personne. Les opérations servent des actions utilisateur : rejeter une contribution, propager un changement de périmètre. Elles traitent une paire ou une contribution source à la fois.

La construction du stock relève du pipeline, qui écrit en SQL ensembliste : la phase `contributions` (`build_contributions.py`) reconstruit les contributions depuis les contributions sources, les phases `normalize`, `affiliations`, `countries` et `persons` alimentent les contributions sources.
"""

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.pipeline.source_contribution_perimeter import (
    SourceContributionPerimeterRecompute,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import NotFoundError
from domain.types import JsonValue


def reject_pair(
    publication_id: int,
    person_id: int,
    *,
    conn: Connection,
    repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository | None = None,
) -> dict[str, int]:
    """Rejette durablement une paire (publication, personne) : enregistre que cette personne n'est pas l'auteur de cette publication.

    Opération unique partagée par les deux façons de rejeter une contribution (depuis la fiche personne et depuis la fiche publication). Quatre effets :

    1. Enregistre la paire dans `rejected_contributions`. Ce registre est consulté par le matching des personnes et par le rebuild des `contributions`, qui écartent toute paire rejetée : le rejet survit aux exécutions suivantes du pipeline.
    2. Met à NULL le `person_id` de toutes les `source_contributions` de la paire, sur toutes les sources, et celui du groupe de la personne dans la publication : le lien disparaît côté données sources, et la forme de nom correspondante cesse de lui être attribuée.
    3. Supprime la ligne consolidée dans `contributions`, qu'aucune source n'atteste.
    4. Recalcule l'appartenance au périmètre de la publication.

    Retourne {"detached": N, "deleted_contributions": M}.
    """
    repo.reject_contribution(publication_id, person_id)
    detached = repo.detach_rejected_pair(publication_id, person_id)
    deleted = repo.delete_orphan_contributions_for_person(person_id)
    perimeter_recompute.refresh_publications(conn, [publication_id])

    emit_event(
        audit_repo,
        "contribution.rejected",
        "publication",
        publication_id,
        {"person_id": person_id},
    )
    return {"detached": detached, "deleted_contributions": deleted}


def exclude_contribution(
    contribution_id: int,
    *,
    conn: Connection,
    repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    person_repo: PersonRepository | None = None,
    audit_repo: AuditRepository | None = None,
) -> dict[str, JsonValue]:
    """Rejette une contribution à partir de son groupe (`source_contribution_groups`).

    Retrouve la paire (publication, personne) à partir du groupe `contribution_id` puis applique `reject_pair`. Si `person_repo` est fourni, supprime ensuite les formes de nom de la personne qu'aucune source restante n'atteste.

    Lève NotFoundError si le groupe n'existe pas ou n'a pas de personne.
    """
    row = repo.get_contribution_person(contribution_id)
    if not row:
        raise NotFoundError(f"Contribution {contribution_id} introuvable")

    person_id = row["person_id"]
    publication_id = row["publication_id"]
    reject_pair(
        publication_id,
        person_id,
        conn=conn,
        repo=repo,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit_repo,
    )
    if person_repo is not None:
        person_repo.delete_orphan_name_forms_for_person(person_id)
    return {"id": contribution_id, "person_id": person_id, "publication_id": publication_id}


def propagate_in_perimeter_for_addresses(
    conn: Connection,
    address_ids: list[int],
    *,
    repo: ContributionRepository,
    perimeter_structures: PerimeterStructures,
    perimeter_recompute: SourceContributionPerimeterRecompute,
) -> None:
    """Recalcule le périmètre des contributions sources liées aux adresses données, de leurs contributions et de leurs publications.

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


def delete_orphan_contributions(person_id: int, *, repo: ContributionRepository) -> int:
    """Supprime les contributions canoniques d'une personne qu'aucune contribution source n'atteste. Retourne le nombre de contributions supprimées."""
    return repo.delete_orphan_contributions_for_person(person_id)
