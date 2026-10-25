"""Command handlers des écritures API sur les contributions : frontière transactionnelle de l'agrégat.

`assign_orphan_contribution` compose deux agrégats : il peut créer la personne cible (`PersonRepository.create`) avant de lui rattacher la contribution, dans une seule transaction.
"""

from sqlalchemy import Connection

from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.contributions import assign_orphans, core as contributions_service
from domain.errors import ValidationError


def exclude_contribution(
    conn: Connection,
    contribution_id: int,
    *,
    repo: ContributionRepository,
    person_repo: PersonRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
) -> None:
    """Rejette une contribution (paire publication/personne) et la détache. Action à sens unique.

    `contribution_id` désigne une contribution rattachée à une personne.
    """
    contributions_service.exclude_contribution(
        contribution_id,
        conn=conn,
        repo=repo,
        perimeter_recompute=perimeter_recompute,
        person_repo=person_repo,
        audit_repo=audit_repo,
    )
    conn.commit()


def assign_orphan_contribution(
    conn: Connection,
    contribution_id: int,
    *,
    person_id: int | None = None,
    new_person: tuple[str, str] | None = None,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue une contribution orpheline, groupe `contribution_id` sans personne, à une personne, en créant celle-ci au besoin (`new_person` = (nom, prénom)). Création et rattachement sont atomiques.

    L'un de `person_id` ou `new_person` est exigé : la commande rattache à une personne, qu'elle reçoive laquelle ou de quoi la créer. Sans l'un ni l'autre, elle lève `ValidationError`.

    Retourne l'id de la personne finalement rattachée.
    """
    if new_person is not None:
        person_id = repo.create(new_person[0], new_person[1])
    if person_id is None:
        raise ValidationError("person_id ou create_person requis")
    assign_orphans.assign_orphan_contribution(
        person_id,
        contribution_id,
        conn=conn,
        repo=repo,
        contribution_repo=contribution_repo,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit_repo,
        force=force,
    )
    conn.commit()
    return person_id


def batch_assign_orphan_contributions(
    conn: Connection,
    person_id: int,
    group_ids: list[int],
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue plusieurs contributions orphelines, groupes sans personne, à une même personne. Retourne le nombre de groupes rattachés."""
    assigned = assign_orphans.batch_assign_orphan_contributions(
        person_id,
        group_ids,
        conn=conn,
        repo=repo,
        contribution_repo=contribution_repo,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit_repo,
        force=force,
    )
    conn.commit()
    return assigned
