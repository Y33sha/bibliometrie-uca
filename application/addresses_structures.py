"""
Service Liens adresse ↔ structure — validation manuelle des
détections de périmètre.

Séparé de `application/addresses.py` depuis §2.9.SRP : la validation
adresse↔structure (confirm / reject / reset / batch) et l'attribution
des pays sont deux responsabilités distinctes, orchestrées par des
routers différents. La gestion des pays vit dans
`application/addresses_countries.py`.

Chaque opération propage automatiquement l'UCA via
`propagate_uca_for_addresses` (recalcul `in_perimeter` sur
`source_authorships`).

Le SQL vit dans `infrastructure/repositories/address_repository.py`.
"""

from typing import Any

from application.authorships import propagate_uca_for_addresses
from application.ports.perimeter import AsyncPerimeterQueries
from domain.ports.address_repository import AsyncAddressRepository
from domain.ports.authorship_repository import AsyncAuthorshipRepository


async def review_structure_link(
    cur: Any,
    address_id: int,
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AsyncAddressRepository,
    authorship_repo: AsyncAuthorshipRepository,
    perimeter_queries: AsyncPerimeterQueries,
) -> None:
    """Upsert le lien address ↔ structure (validation manuelle).

    - is_confirmed = True  → confirme (crée le lien si besoin)
    - is_confirmed = False → rejette (crée le lien si besoin)
    - is_confirmed = None  → reset (supprime le lien manuel, remet l'auto à NULL)

    Propage l'UCA aux source_authorships et authorships vérité **uniquement
    si la contribution de l'adresse au calcul in_perimeter change**.
    Évite les cascades massives sur les opérations no-op (ex: confirmer
    manuellement une adresse UCA déjà auto-détectée, 67k+ rows inutilement
    mises à jour → 504 timeout).
    """
    before = await repo.which_contribute_to_perimeter([address_id], structure_id)

    if is_confirmed is None:
        await repo.reset_manual_link(address_id, structure_id)
    else:
        await repo.upsert_structure_link(address_id, structure_id, is_confirmed)

    after = await repo.which_contribute_to_perimeter([address_id], structure_id)

    if before != after:
        await propagate_uca_for_addresses(
            cur, [address_id], repo=authorship_repo, perimeter_queries=perimeter_queries
        )


async def batch_review_structure_link(
    cur: Any,
    address_ids: list[int],
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AsyncAddressRepository,
    authorship_repo: AsyncAuthorshipRepository,
    perimeter_queries: AsyncPerimeterQueries,
) -> int:
    """Comme review_structure_link mais sur un lot d'adresses.

    Retourne le nombre d'adresses touchées (pour les reset, nombre de lignes
    UPDATEes ; pour les upserts, taille du lot passé).

    Propage uniquement pour les adresses dont la contribution au calcul
    in_perimeter a effectivement changé.
    """
    if not address_ids:
        return 0

    before = await repo.which_contribute_to_perimeter(address_ids, structure_id)

    if is_confirmed is None:
        updated = await repo.batch_reset_manual_links(address_ids, structure_id)
    else:
        await repo.batch_upsert_structure_links(address_ids, structure_id, is_confirmed)
        updated = len(address_ids)

    after = await repo.which_contribute_to_perimeter(address_ids, structure_id)

    changed = list(before ^ after)
    if changed:
        await propagate_uca_for_addresses(
            cur, changed, repo=authorship_repo, perimeter_queries=perimeter_queries
        )
    return updated


async def unassign_manual_structure(
    cur: Any,
    address_id: int,
    structure_id: int,
    *,
    repo: AsyncAddressRepository,
    authorship_repo: AsyncAuthorshipRepository,
    perimeter_queries: AsyncPerimeterQueries,
) -> bool:
    """Supprime uniquement le lien manuel (matched_form_id IS NULL) entre
    une adresse et une structure. Les liens auto-détectés et leurs is_confirmed
    ne sont pas touchés (contrairement à review_structure_link(None)).

    Propage l'UCA uniquement si la contribution de l'adresse au calcul
    in_perimeter change effectivement.
    Retourne True si un lien manuel a été supprimé, False sinon.
    """
    before = await repo.which_contribute_to_perimeter([address_id], structure_id)
    deleted = await repo.delete_manual_structure_link(address_id, structure_id)
    after = await repo.which_contribute_to_perimeter([address_id], structure_id)

    if before != after:
        await propagate_uca_for_addresses(
            cur, [address_id], repo=authorship_repo, perimeter_queries=perimeter_queries
        )
    return deleted
