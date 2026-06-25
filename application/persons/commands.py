"""Command handlers des écritures API sur les personnes : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Chaque handler
reçoit la connexion de la requête, compose les briques agnostiques de `core.py`
et `conn.commit()` au succès — pour que la donnée soit persistée avant l'envoi de
la réponse (cf. `docs/chantiers/CODE_commit-avant-reponse.md`). Les briques
composées restent transaction-agnostiques (réutilisées par le pipeline et les
CLI) ; seul le command handler commit.

Couvre les tables de l'agrégat : `persons`, `person_identifiers`,
`person_name_forms`, ainsi que le rattachement des `source_authorships` (le
`person_id` y est la source de vérité du lien personne).
"""

from sqlalchemy import Connection

from application.persons import core as persons_service
from application.persons.core import AuthorshipRef, DetachResult
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import (
    IdentifierStatusRow,
    NameFormStatusRow,
    PersonRepository,
)

# ── Identifiants ──────────────────────────────────────────────────


def add_identifier(
    conn: Connection,
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    source: str = "manual",
    repo: PersonRepository,
) -> None:
    """Ajoute un identifiant (ORCID/idHAL) à une personne."""
    persons_service.add_identifier(person_id, id_type, id_value, source=source, repo=repo)
    conn.commit()


def remove_identifier(
    conn: Connection,
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Supprime un identifiant d'une personne."""
    persons_service.remove_identifier(
        person_id, id_type, id_value, repo=repo, audit_repo=audit_repo
    )
    conn.commit()


def update_identifier_status(
    conn: Connection,
    ident_id: int,
    status: str,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> IdentifierStatusRow:
    """Met à jour le statut d'un identifiant. Retourne la ligne {id, status, person_id}."""
    row = persons_service.update_identifier_status(
        ident_id, status, repo=repo, audit_repo=audit_repo
    )
    conn.commit()
    return row


def reassign_identifier(
    conn: Connection,
    ident_id: int,
    target_person_id: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Réattribue un identifiant rejeté à une autre personne (status → pending)."""
    persons_service.reassign_identifier(
        ident_id, target_person_id, repo=repo, audit_repo=audit_repo
    )
    conn.commit()


# ── Rejet / renommage / fusion ────────────────────────────────────


def set_rejected(
    conn: Connection,
    person_id: int,
    rejected: bool,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Marque/démarque une personne comme rejetée."""
    persons_service.set_rejected(person_id, rejected, repo=repo, audit_repo=audit_repo)
    conn.commit()


def update_name(
    conn: Connection,
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
) -> None:
    """Modifie le nom/prénom d'une personne (et rafraîchit ses formes de nom)."""
    persons_service.update_name(person_id, last_name, first_name, repo=repo)
    conn.commit()


def merge_person(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Fusionne la personne source dans la cible (refus si RH distinctes des deux côtés)."""
    persons_service.merge_person(target_id, source_id, repo=repo, audit_repo=audit_repo)
    conn.commit()


def mark_distinct(
    conn: Connection,
    person_id_a: int,
    person_id_b: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> None:
    """Marque deux personnes comme distinctes (non-doublon). Idempotent."""
    persons_service.mark_distinct(person_id_a, person_id_b, repo=repo, audit_repo=audit_repo)
    conn.commit()


# ── Formes de noms / détachement authorships ──────────────────────


def detach_authorships(
    conn: Connection,
    person_id: int,
    authorships: list[AuthorshipRef],
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository,
) -> DetachResult:
    """Rejette durablement les paires (publication, personne) des authorships
    sélectionnées et nettoie les formes de noms orphelines.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_forms": K}."""
    result = persons_service.detach_authorships(
        person_id,
        authorships,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit_repo,
    )
    conn.commit()
    return result


def update_name_form_status(
    conn: Connection,
    person_id: int,
    name_form: str,
    status: str,
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository,
) -> NameFormStatusRow:
    """Met à jour le statut d'une forme de nom. `rejected` détache aussi les
    signatures portant la forme. Retourne la ligne {person_id, name_form, status}."""
    row = persons_service.update_name_form_status(
        person_id,
        name_form,
        status,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit_repo,
    )
    conn.commit()
    return row
