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

    Propage automatiquement l'UCA aux source_authorships et authorships vérité.
    """
    if is_confirmed is None:
        await repo.reset_manual_link(address_id, structure_id)
    else:
        await repo.upsert_structure_link(address_id, structure_id, is_confirmed)
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
    """
    if not address_ids:
        return 0

    if is_confirmed is None:
        updated = await repo.batch_reset_manual_links(address_ids, structure_id)
    else:
        await repo.batch_upsert_structure_links(address_ids, structure_id, is_confirmed)
        updated = len(address_ids)

    await propagate_uca_for_addresses(
        cur, address_ids, repo=authorship_repo, perimeter_queries=perimeter_queries
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

    Propage automatiquement l'UCA.
    Retourne True si un lien manuel a été supprimé, False sinon.
    """
    deleted = await repo.delete_manual_structure_link(address_id, structure_id)
    await propagate_uca_for_addresses(
        cur, [address_id], repo=authorship_repo, perimeter_queries=perimeter_queries
    )
    return deleted
