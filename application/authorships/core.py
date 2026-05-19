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
from domain.errors import NotFoundError, ValidationError
from domain.json_types import JsonValue
from domain.sources import ALL_SOURCES_SET as VALID_SOURCES


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


def set_source_authorship_excluded(
    source_authorship_id: int,
    source: str,
    excluded: bool,
    *,
    repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Marque ou démarque une authorship source comme exclue.

    Si `excluded=True`, détache aussi la FK vers l'authorship canonique et
    supprime cette dernière si plus aucune source non-exclue ne l'atteste.

    Lève ValidationError si la source n'est pas reconnue.
    Lève NotFoundError si l'authorship source n'existe pas.
    """
    if source not in VALID_SOURCES:
        raise ValidationError(f"Source inconnue : {source}")

    if not repo.set_source_authorship_excluded(source_authorship_id, source, excluded):
        raise NotFoundError(f"Authorship source {source}:{source_authorship_id} introuvable")

    if excluded:
        detach_source(source_authorship_id, source, repo=repo)

    emit_event(
        audit_repo,
        "source_authorship.excluded",
        "source_authorship",
        source_authorship_id,
        {"source": source, "excluded": excluded},
    )


def detach_source(source_authorship_id: int, source: str, *, repo: AuthorshipRepository) -> bool:
    """Détache une authorship source de son authorship canonique.
    Si plus aucune source ne l'atteste, supprime l'authorship canonique.

    Retourne True si l'authorship canonique a été supprimée, False sinon.
    Lève ValidationError si la source n'est pas reconnue.
    """
    if source not in VALID_SOURCES:
        raise ValidationError(f"Source inconnue : {source}")

    authorship_id = repo.get_authorship_id_for_source(source_authorship_id, source)
    if not authorship_id:
        return False

    repo.clear_source_authorship_fk(source_authorship_id, source)

    if not repo.has_active_source_attestation(authorship_id):
        repo.delete_authorship(authorship_id)
        return True
    return False


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
