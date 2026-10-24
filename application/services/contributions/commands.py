"""Command handlers des écritures API sur les contributions : frontière transactionnelle de l'agrégat.

`assign_orphan_contribution` compose deux agrégats : il peut créer la personne cible (`persons.core.create_person`) avant de lui rattacher la contribution, dans une seule transaction.
"""

from sqlalchemy import Connection

from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.contributions import assign_orphans, core as contributions_service
from application.services.persons import core as persons_service
from domain.errors import ValidationError


def exclude_contribution(
    conn: Connection,
    contribution_id: int,
    *,
    repo: ContributionRepository,
    person_repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Rejette une contribution (paire publication/personne) et la détache. Action à sens unique.

    `contribution_id` désigne un groupe de `source_contribution_groups` rattaché à une personne, quand les gestes sur les orphelines adressent une contribution source.
    """
    contributions_service.exclude_contribution(
        contribution_id, repo=repo, person_repo=person_repo, audit_repo=audit_repo
    )
    conn.commit()


def assign_orphan_contribution(
    conn: Connection,
    source_contribution_id: int,
    *,
    person_id: int | None = None,
    new_person: tuple[str, str] | None = None,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue une contribution orpheline à une personne, en créant celle-ci au besoin (`new_person` = (nom, prénom)). Création et rattachement sont atomiques.

    L'un de `person_id` ou `new_person` est exigé : la commande rattache à une personne, qu'elle reçoive laquelle ou de quoi la créer. Sans l'un ni l'autre, elle lève `ValidationError`.

    Retourne l'id de la personne finalement rattachée.
    """
    if new_person is not None:
        person_id = persons_service.create_person(new_person[0], new_person[1], repo=repo)
    if person_id is None:
        raise ValidationError("person_id ou create_person requis")
    assign_orphans.assign_orphan_contribution(
        person_id,
        source_contribution_id,
        repo=repo,
        contribution_repo=contribution_repo,
        audit_repo=audit_repo,
        force=force,
    )
    conn.commit()
    return person_id


def batch_assign_orphan_contributions(
    conn: Connection,
    person_id: int,
    source_contribution_ids: list[int],
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue plusieurs contributions orphelines à une même personne. Retourne le nombre assigné."""
    assigned = assign_orphans.batch_assign_orphan_contributions(
        person_id,
        source_contribution_ids,
        conn=conn,
        repo=repo,
        contribution_repo=contribution_repo,
        audit_repo=audit_repo,
        force=force,
    )
    conn.commit()
    return assigned
