"""
Service Authorships — orchestrateur des opérations sur `authorships`
et `source_authorships`.

Opérations unitaires sur les authorships consolidées. Le script batch
`build_authorships.py` reste le constructeur principal (reconstruction
complète).

Le SQL vit dans `infrastructure/repositories/authorship_repository.py`.
"""

from sqlalchemy import Connection

from application.audit import emit_event
from application.ports.pipeline.perimeter import PerimeterQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from domain.errors import NotFoundError
from domain.types import JsonValue


def exclude_authorship(
    authorship_id: int,
    *,
    repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
) -> dict[str, JsonValue]:
    """Marque une authorship comme exclue et détache les authorships sources.

    1. Marque l'authorship excluded = TRUE
    2. Met person_id = NULL sur les authorships sources liées
       (pour que build_authorships ne recrée pas le lien)

    Lève NotFoundError si l'authorship n'existe pas.
    """
    row = repo.get_authorship_person(authorship_id)
    if not row:
        raise NotFoundError(f"Authorship {authorship_id} introuvable")

    person_id = row["person_id"]
    result = repo.mark_authorship_excluded(authorship_id)
    if person_id:
        repo.detach_source_authorships_for_person(authorship_id, person_id)

    emit_event(
        audit_repo,
        "authorship.excluded",
        "authorship",
        authorship_id,
        {"person_id": person_id},
    )
    return result


def propagate_uca_for_addresses(
    conn: Connection,
    address_ids: list[int],
    *,
    repo: AuthorshipRepository,
    perimeter_queries: PerimeterQueries,
) -> None:
    """Recalcule in_perimeter sur source_authorships et authorships canoniques
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    perimeter_ids = perimeter_queries.get_persons_structure_ids_list(conn)
    if not perimeter_ids:
        return

    affected_sa_ids = repo.find_source_authorships_by_addresses(address_ids)
    if not affected_sa_ids:
        return

    repo.recompute_in_perimeter_on_source_authorships(affected_sa_ids, perimeter_ids)
    repo.propagate_in_perimeter_to_authorships(affected_sa_ids)


def delete_orphan_authorships(person_id: int, *, repo: AuthorshipRepository) -> int:
    """Supprime les authorships canoniques d'une personne qui ne sont plus
    attestées par aucune authorship source. Retourne le nombre d'authorships
    supprimées.
    """
    return repo.delete_orphan_authorships_for_person(person_id)
