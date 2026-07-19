"""Command handlers des écritures API sur les authorships : frontière transactionnelle de l'agrégat.

`assign_orphan_authorship` compose deux agrégats : il peut créer la personne cible (`persons.core.create_person`) avant de lui rattacher l'authorship, dans une seule transaction.
"""

from sqlalchemy import Connection

from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.authorships import assign_orphans, core as authorships_service
from application.services.persons import core as persons_service
from domain.errors import ValidationError


def exclude_authorship(
    conn: Connection,
    authorship_id: int,
    *,
    repo: AuthorshipRepository,
    person_repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Rejette une contribution (paire publication/personne) et la détache. Action à sens unique."""
    authorships_service.exclude_authorship(
        authorship_id, repo=repo, person_repo=person_repo, audit_repo=audit_repo
    )
    conn.commit()


def assign_orphan_authorship(
    conn: Connection,
    authorship_id: int,
    *,
    person_id: int | None = None,
    new_person: tuple[str, str] | None = None,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue une authorship orpheline à une personne, en créant celle-ci au besoin (`new_person` = (nom, prénom)). Création et rattachement sont atomiques.

    L'un de `person_id` ou `new_person` est exigé : la commande rattache à une personne, qu'elle reçoive laquelle ou de quoi la créer. Sans l'un ni l'autre, elle lève `ValidationError`.

    Retourne l'id de la personne finalement rattachée.
    """
    if new_person is not None:
        person_id = persons_service.create_person(new_person[0], new_person[1], repo=repo)
    if person_id is None:
        raise ValidationError("person_id ou create_person requis")
    assign_orphans.assign_orphan_authorship(
        person_id,
        authorship_id,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit_repo,
        force=force,
    )
    conn.commit()
    return person_id


def batch_assign_orphan_authorships(
    conn: Connection,
    person_id: int,
    source_authorship_ids: list[int],
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue plusieurs authorships orphelines à une même personne. Retourne le nombre assigné."""
    assigned = assign_orphans.batch_assign_orphan_authorships(
        person_id,
        source_authorship_ids,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit_repo,
        force=force,
    )
    conn.commit()
    return assigned
