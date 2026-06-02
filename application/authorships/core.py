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
    """Rejette une authorship canonique : « cette personne n'est PAS l'auteur ».

    1. Enregistre la paire (publication, personne) dans `rejected_authorships`
       — store univoque qui survit aux rebuilds (les sites de création
       d'authorships anti-joignent ce store).
    2. Supprime la row `authorships` (les FK nettoient `authorship_structures`
       et délient `source_authorships.authorship_id`).

    La vérité source (`source_authorships.person_id`) n'est pas touchée.

    Lève NotFoundError si l'authorship n'existe pas.
    """
    row = repo.get_authorship_person(authorship_id)
    if not row:
        raise NotFoundError(f"Authorship {authorship_id} introuvable")

    person_id = row["person_id"]
    publication_id = row["publication_id"]
    if person_id is not None:
        repo.reject_authorship(publication_id, person_id)
    repo.delete_authorship(authorship_id)

    emit_event(
        audit_repo,
        "authorship.rejected",
        "authorship",
        authorship_id,
        {"person_id": person_id, "publication_id": publication_id},
    )
    return {"id": authorship_id, "person_id": person_id, "publication_id": publication_id}


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
    # Les structures dérivées vivent dans la matview `authorship_structures` :
    # un refresh global la réaligne après la propagation ciblée (~2 s).
    repo.refresh_authorship_structures()


def delete_orphan_authorships(person_id: int, *, repo: AuthorshipRepository) -> int:
    """Supprime les authorships canoniques d'une personne qui ne sont plus
    attestées par aucune authorship source. Retourne le nombre d'authorships
    supprimées.
    """
    return repo.delete_orphan_authorships_for_person(person_id)
