"""Service Liens adresse ↔ structure — validation manuelle des détections de périmètre.

La validation adresse ↔ structure (confirm / reject / reset / batch) et l'attribution des pays sont deux responsabilités distinctes, orchestrées par des routers différents ; les pays vivent dans `application/services/addresses/countries.py`.

Ces opérations écrivent le lien et **retournent les adresses dont la contribution au calcul `in_perimeter` a changé**. La propagation (`propagate_in_perimeter_for_addresses`, potentiellement massive — jusqu'à des dizaines de milliers de source_authorships) est lancée en tâche de fond par l'appelant (`bg_propagate_in_perimeter_sync`), jamais synchrone dans la requête.
"""

from application.ports.repositories.address_repository import AddressRepository


def review_structure_link(
    address_id: int,
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
) -> list[int]:
    """Insère ou met à jour le lien adresse ↔ structure (validation manuelle).

    - is_confirmed = True  → confirme (crée le lien si besoin)
    - is_confirmed = False → rejette (crée le lien si besoin)
    - is_confirmed = None  → reset (supprime le lien manuel, remet l'auto à NULL)

    Retourne `[address_id]` si la contribution de l'adresse au calcul in_perimeter a changé (à propager en tâche de fond), `[]` sinon — ce qui évite les cascades massives sur les no-op (ex : confirmer une adresse déjà auto-détectée).
    """
    before = repo.which_contribute_to_perimeter([address_id], structure_id)

    if is_confirmed is None:
        repo.reset_manual_link(address_id, structure_id)
    else:
        repo.upsert_structure_link(address_id, structure_id, is_confirmed)

    after = repo.which_contribute_to_perimeter([address_id], structure_id)
    return list(before ^ after)


def batch_review_structure_link(
    address_ids: list[int],
    structure_id: int,
    is_confirmed: bool | None,
    *,
    repo: AddressRepository,
) -> tuple[int, list[int]]:
    """Comme `review_structure_link` mais sur un lot d'adresses.

    Retourne `(nombre d'adresses touchées, adresses dont la contribution au calcul in_perimeter a changé)`. Pour les reset, le nombre touché est le nombre de lignes mises à jour ; pour les upserts, la taille du lot. La propagation des adresses changées est lancée en tâche de fond par l'appelant.
    """
    if not address_ids:
        return 0, []

    before = repo.which_contribute_to_perimeter(address_ids, structure_id)

    if is_confirmed is None:
        updated = repo.batch_reset_manual_links(address_ids, structure_id)
    else:
        repo.batch_upsert_structure_links(address_ids, structure_id, is_confirmed)
        updated = len(address_ids)

    after = repo.which_contribute_to_perimeter(address_ids, structure_id)
    return updated, list(before ^ after)
