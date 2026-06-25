"""Command handlers des écritures API sur les authorships : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Chaque handler
reçoit la connexion de la requête, compose les briques agnostiques de `core.py` /
`assign_orphans.py` et `conn.commit()` au succès — pour que la donnée soit
persistée avant l'envoi de la réponse (cf.
`docs/chantiers/CODE_commit-avant-reponse.md`). Les briques composées restent
transaction-agnostiques (réutilisées par le pipeline et les CLI) ; seul le
command handler commit.

`assign_orphan_authorship` compose deux agrégats : il peut créer la personne
cible (`persons.core.create_person`) puis lui rattacher l'authorship, le tout
dans une seule transaction.
"""

from sqlalchemy import Connection

from application.authorships import assign_orphans, core as authorships_service
from application.persons import core as persons_service
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository


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
    source: str,
    authorship_id: int,
    *,
    person_id: int | None = None,
    new_person: tuple[str, str] | None = None,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository,
    force: bool = False,
) -> int:
    """Attribue une authorship orpheline à une personne, en créant celle-ci au
    besoin (`new_person` = (nom, prénom)). Création + rattachement sont atomiques.

    Retourne l'id de la personne finalement rattachée.
    """
    if new_person is not None:
        person_id = persons_service.create_person(new_person[0], new_person[1], repo=repo)
    assert person_id is not None
    assign_orphans.assign_orphan_authorship(
        person_id,
        source,
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
