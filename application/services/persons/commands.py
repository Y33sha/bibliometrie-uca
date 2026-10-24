"""Command handlers des écritures API sur les personnes : frontière transactionnelle de l'agrégat.

Couvre `persons`, `person_identifiers`, `person_name_forms`, et le rattachement des `source_contributions`, où le `person_id` matérialise le lien vers la personne.
"""

from sqlalchemy import Connection

from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import (
    NameFormStatusRow,
    PersonRepository,
)
from application.services.persons import core as persons_service
from application.services.persons.core import (
    AddIdentifierResult,
    ContributionRef,
    DetachResult,
    IdentifierStatusResult,
)
from domain.persons.identifiers import IdentifierOrigin
from domain.persons.person import PersonExclusion

# ── Identifiants ──────────────────────────────────────────────────


def add_identifier(
    conn: Connection,
    person_id: int,
    id_type: str,
    id_value: str,
    *,
    source: IdentifierOrigin = IdentifierOrigin.MANUAL,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> AddIdentifierResult:
    """Ajoute un identifiant (ORCID/idHAL) à une personne. Retourne l'issue de la cascade."""
    result = persons_service.add_identifier(
        person_id, id_type, id_value, source=source, repo=repo, audit_repo=audit_repo
    )
    conn.commit()
    return result


def update_identifier_status(
    conn: Connection,
    ident_id: int,
    status: str,
    *,
    repo: PersonRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
) -> IdentifierStatusResult:
    """Met à jour le statut d'un identifiant, et celui des identifiants de ses comptes HAL. Un rejet détache les groupes rattachés par les identifiants rejetés."""
    result = persons_service.update_identifier_status(
        ident_id,
        status,
        conn=conn,
        repo=repo,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit_repo,
    )
    conn.commit()
    return result


# ── Exclusion / renommage / fusion ────────────────────────────────


def set_exclusion(
    conn: Connection,
    person_id: int,
    exclusion: PersonExclusion | None,
    *,
    repo: PersonRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
) -> None:
    """Exclut ou retient une personne."""
    persons_service.set_exclusion(
        person_id,
        exclusion,
        conn=conn,
        repo=repo,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit_repo,
    )
    conn.commit()


def update_name(
    conn: Connection,
    person_id: int,
    last_name: str,
    first_name: str,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Modifie le nom/prénom d'une personne (et rafraîchit ses formes de nom)."""
    persons_service.update_name(person_id, last_name, first_name, repo=repo, audit_repo=audit_repo)
    conn.commit()


def merge_person(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository,
) -> tuple[int, int]:
    """Fusionne deux personnes et retourne (id conservé, id absorbé) ; la personne qui a une fiche RH est conservée."""
    merged = persons_service.merge_person(target_id, source_id, repo=repo, audit_repo=audit_repo)
    conn.commit()
    return merged


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


# ── Formes de noms / détachement contributions ──────────────────────


def detach_contributions(
    conn: Connection,
    person_id: int,
    contributions: list[ContributionRef],
    *,
    repo: PersonRepository,
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
) -> DetachResult:
    """Rejette durablement les paires (publication, personne) des contributions sélectionnées et nettoie les formes de noms orphelines.

    Retourne {"detached": N, "cleaned_forms": K}."""
    result = persons_service.detach_contributions(
        person_id,
        contributions,
        conn=conn,
        repo=repo,
        contribution_repo=contribution_repo,
        perimeter_recompute=perimeter_recompute,
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
    contribution_repo: ContributionRepository,
    perimeter_recompute: PublicationPerimeterRecompute,
    audit_repo: AuditRepository,
) -> NameFormStatusRow:
    """Met à jour le statut d'une forme de nom. `rejected` détache aussi les contributions sources et les groupes sous cette forme. Retourne la ligne {person_id, name_form, status}."""
    row = persons_service.update_name_form_status(
        person_id,
        name_form,
        status,
        conn=conn,
        repo=repo,
        contribution_repo=contribution_repo,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit_repo,
    )
    conn.commit()
    return row
