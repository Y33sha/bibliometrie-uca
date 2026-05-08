"""
Service Authorships vérité — orchestrateur des opérations sur
`authorships` et `source_authorships`.

Opérations unitaires sur les authorships consolidées. Le script batch
`build_authorships.py` reste le constructeur principal (reconstruction
complète), et `webapp/uca.py` gère le recalcul UCA incrémental.

Le SQL vit dans `infrastructure/repositories/async_authorship_repository.py`.
"""

from typing import Any

from application.audit import async_emit_event
from application.ports.perimeter import AsyncPerimeterQueries
from domain.errors import NotFoundError, ValidationError
from domain.ports.authorship_repository import AsyncAuthorshipRepository
from domain.sources import BIBLIO_SOURCES as VALID_SOURCES


async def exclude_authorship(
    cur: Any, authorship_id: int, *, repo: AsyncAuthorshipRepository
) -> dict:
    """Marque une authorship vérité comme exclue et détache les authorships sources.

    1. Marque l'authorship vérité excluded = TRUE
    2. Met person_id = NULL sur les authorships sources liées
       (pour que build_authorships ne recrée pas le lien)

    Lève NotFoundError si l'authorship n'existe pas.
    """
    row = await repo.get_authorship_person(authorship_id)
    if not row:
        raise NotFoundError(f"Authorship {authorship_id} introuvable")

    person_id = row["person_id"]
    result = await repo.mark_authorship_excluded(authorship_id)
    if person_id:
        await repo.detach_source_authorships_for_person(authorship_id, person_id)

    await async_emit_event(
        cur,
        "authorship.excluded",
        "authorship",
        authorship_id,
        {"person_id": person_id},
    )
    return result


async def set_source_authorship_excluded(
    cur: Any,
    source_authorship_id: int,
    source: str,
    excluded: bool,
    *,
    repo: AsyncAuthorshipRepository,
) -> None:
    """Marque ou démarque une authorship source comme exclue.

    Si `excluded=True`, détache aussi la FK vers l'authorship vérité et
    supprime cette dernière si plus aucune source non-exclue ne l'atteste.

    Lève ValidationError si la source n'est pas reconnue.
    Lève NotFoundError si l'authorship source n'existe pas.
    """
    if source not in VALID_SOURCES:
        raise ValidationError(f"Source inconnue : {source}")

    if not await repo.set_source_authorship_excluded(source_authorship_id, source, excluded):
        raise NotFoundError(f"Authorship source {source}:{source_authorship_id} introuvable")

    if excluded:
        await detach_source(cur, source_authorship_id, source, repo=repo)

    await async_emit_event(
        cur,
        "source_authorship.excluded",
        "source_authorship",
        source_authorship_id,
        {"source": source, "excluded": excluded},
    )


async def detach_source(
    cur: Any, source_authorship_id: int, source: str, *, repo: AsyncAuthorshipRepository
) -> bool:
    """Détache une authorship source de son authorship vérité.
    Si plus aucune source ne l'atteste, supprime l'authorship vérité.

    Retourne True si l'authorship vérité a été supprimée, False sinon.
    Lève ValidationError si la source n'est pas reconnue.
    """
    if source not in VALID_SOURCES:
        raise ValidationError(f"Source inconnue : {source}")

    truth_id = await repo.get_source_authorship_truth_id(source_authorship_id, source)
    if not truth_id:
        return False

    await repo.clear_source_authorship_fk(source_authorship_id, source)

    if not await repo.has_active_source_attestation(truth_id):
        await repo.delete_authorship(truth_id)
        return True
    return False


async def async_delete_orphan_authorships(
    cur: Any, person_id: int, *, repo: AsyncAuthorshipRepository
) -> int:
    """Supprime les authorships vérité d'une personne qui ne sont plus attestées
    par aucune authorship source.
    Retourne le nombre d'authorships supprimées.
    """
    return await repo.delete_orphan_authorships_for_person(person_id)


async def propagate_uca_for_addresses(
    cur: Any,
    address_ids: list[int],
    *,
    repo: AsyncAuthorshipRepository,
    perimeter_queries: AsyncPerimeterQueries,
) -> None:
    """Recalcule in_perimeter sur source_authorships et authorships vérité
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    perimeter_ids = await perimeter_queries.get_persons_structure_ids_list(cur)
    if not perimeter_ids:
        return

    affected_sa_ids = await repo.find_source_authorships_by_addresses(address_ids)
    if not affected_sa_ids:
        return

    await repo.recompute_in_perimeter_on_source_authorships(affected_sa_ids, perimeter_ids)
    await repo.propagate_in_perimeter_to_truth_authorships(affected_sa_ids)
