"""Validation manuelle des rattachements adresse ↔ structure (table `address_structures`) : confirmer, rejeter ou réinitialiser une détection de la phase `affiliations`.

Ces opérations écrivent le lien et rendent les adresses dont la contribution au calcul `in_perimeter` a changé. Leur propagation (`propagate_in_perimeter_for_addresses`) peut toucher des dizaines de milliers de contributions sources : l'appelant la lance en tâche de fond.
"""

from application.audit_log import emit_event
from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.pipeline.source_contribution_perimeter import (
    SourceContributionPerimeterRecompute,
)
from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.contribution_repository import ContributionRepository


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
    emit_event(
        "address.link_reviewed",
        "address",
        address_id,
        {"structure_id": structure_id, "is_confirmed": is_confirmed},
    )
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

    Un lot est une décision unique : l'événement d'audit est unique lui aussi, sans identifiant d'agrégat, et contient les adresses visées et le nombre effectivement touché.
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
    emit_event(
        "address.batch_link_reviewed",
        "address",
        None,
        {
            "address_ids": address_ids,
            "structure_id": structure_id,
            "is_confirmed": is_confirmed,
            "updated": updated,
        },
    )
    return updated, list(before ^ after)


def propagate_in_perimeter_for_addresses(
    address_ids: list[int],
    *,
    repo: ContributionRepository,
    perimeter_structures: PerimeterStructures,
    perimeter_recompute: SourceContributionPerimeterRecompute,
) -> None:
    """Recalcule le périmètre des contributions sources liées aux adresses données, de leurs groupes et de leurs publications."""
    if not address_ids:
        return

    perimeter_ids = perimeter_structures.persons_structure_ids()
    if not perimeter_ids:
        return

    affected_source_contribution_ids = repo.find_source_contributions_by_addresses(address_ids)
    if not affected_source_contribution_ids:
        return

    perimeter_recompute.recompute_perimeter(affected_source_contribution_ids, perimeter_ids)
