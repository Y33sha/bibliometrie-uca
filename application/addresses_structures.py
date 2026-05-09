"""
Service Liens adresse ↔ structure — validation manuelle des
détections de périmètre.

Séparé de `application/addresses.py` (principe SRP) : la validation
adresse↔structure (confirm / reject / reset / batch) et l'attribution
des pays sont deux responsabilités distinctes, orchestrées par des
routers différents. La gestion des pays vit dans
`application/addresses_countries.py`.

Chaque opération propage automatiquement l'UCA via
`propagate_uca_for_addresses` (recalcul `in_perimeter` sur
`source_authorships`).
"""

from sqlalchemy import Connection

from application.authorships import propagate_uca_for_addresses
from application.ports.perimeter import PerimeterQueries
from domain.ports.address_repository import AddressRepository
from domain.ports.authorship_repository import AuthorshipRepository


def review_structure_link(
    conn: Connection,
    address_id: int,
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
    authorship_repo: AuthorshipRepository,
    perimeter_queries: PerimeterQueries,
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
    before = repo.which_contribute_to_perimeter([address_id], structure_id)

    if is_confirmed is None:
        repo.reset_manual_link(address_id, structure_id)
    else:
        repo.upsert_structure_link(address_id, structure_id, is_confirmed)

    after = repo.which_contribute_to_perimeter([address_id], structure_id)

    if before != after:
        propagate_uca_for_addresses(
            conn, [address_id], repo=authorship_repo, perimeter_queries=perimeter_queries
        )


def batch_review_structure_link(
    conn: Connection,
    address_ids: list[int],
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
    authorship_repo: AuthorshipRepository,
    perimeter_queries: PerimeterQueries,
) -> int:
    """Comme review_structure_link mais sur un lot d'adresses.

    Retourne le nombre d'adresses touchées (pour les reset, nombre de lignes
    UPDATEes ; pour les upserts, taille du lot passé).

    Propage uniquement pour les adresses dont la contribution au calcul
    in_perimeter a effectivement changé.
    """
    if not address_ids:
        return 0

    before = repo.which_contribute_to_perimeter(address_ids, structure_id)

    if is_confirmed is None:
        updated = repo.batch_reset_manual_links(address_ids, structure_id)
    else:
        repo.batch_upsert_structure_links(address_ids, structure_id, is_confirmed)
        updated = len(address_ids)

    after = repo.which_contribute_to_perimeter(address_ids, structure_id)

    changed = list(before ^ after)
    if changed:
        propagate_uca_for_addresses(
            conn, changed, repo=authorship_repo, perimeter_queries=perimeter_queries
        )
    return updated


def unassign_manual_structure(
    conn: Connection,
    address_id: int,
    structure_id: int,
    *,
    repo: AddressRepository,
    authorship_repo: AuthorshipRepository,
    perimeter_queries: PerimeterQueries,
) -> bool:
    """Supprime uniquement le lien manuel (matched_form_id IS NULL) entre
    une adresse et une structure. Les liens auto-détectés et leurs is_confirmed
    ne sont pas touchés (contrairement à review_structure_link(None)).

    Propage l'UCA uniquement si la contribution de l'adresse au calcul
    in_perimeter change effectivement.
    Retourne True si un lien manuel a été supprimé, False sinon.
    """
    before = repo.which_contribute_to_perimeter([address_id], structure_id)
    deleted = repo.delete_manual_structure_link(address_id, structure_id)
    after = repo.which_contribute_to_perimeter([address_id], structure_id)

    if before != after:
        propagate_uca_for_addresses(
            conn, [address_id], repo=authorship_repo, perimeter_queries=perimeter_queries
        )
    return deleted
