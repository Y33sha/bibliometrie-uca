"""Attribution d'un identifiant externe à une personne, et issue d'une nouvelle attribution.

Le statut (`pending`, `confirmed`, `rejected`) qualifie l'attribution.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

from domain.errors import ConflictError
from domain.persons.identifiers import AttributionStatus, IdentifierOrigin


class AttributionOutcome(StrEnum):
    """Issue de l'attribution d'un identifiant à une personne (`attribution_outcome`)."""

    ADDED = "added"  # identifiant absent : inséré en `pending`
    ALREADY_EXISTS = "already_exists"  # déjà attribué à cette personne
    REASSIGNED = "reassigned"  # repris d'une autre personne, chez qui il était `rejected`
    HELD_ELSEWHERE = "held_elsewhere"  # une autre personne le détient en `pending` ou `confirmed`


@dataclass(frozen=True, slots=True)
class IdentifierAttribution:
    """Attribution d'un identifiant externe (ORCID, idHAL, IdRef, compte HAL) à une personne. Une valeur d'identifiant appartient à une seule personne."""

    id: int
    person_id: int
    id_type: str
    id_value: str
    """Valeur sous forme canonique."""
    status: AttributionStatus
    source: IdentifierOrigin | None


class AttributionResult(NamedTuple):
    """Résultat de l'attribution d'un identifiant à une personne."""

    outcome: AttributionOutcome
    id_value: str
    """Valeur normalisée."""
    existing: IdentifierAttribution | None
    """Attribution trouvée en base, à défaut `None`."""


def attribution_outcome(
    existing: IdentifierAttribution | None, person_id: int
) -> AttributionOutcome:
    """Renvoie l'issue de l'attribution d'un identifiant à `person_id`, d'après son attribution en base (`existing`). Un identifiant détenu par une autre personne se reprend seulement après passage de son attribution à `rejected`."""
    if existing is None:
        return AttributionOutcome.ADDED
    if existing.person_id == person_id:
        return AttributionOutcome.ALREADY_EXISTS
    if existing.status is AttributionStatus.REJECTED:
        return AttributionOutcome.REASSIGNED
    return AttributionOutcome.HELD_ELSEWHERE


def held_elsewhere_conflict(existing: IdentifierAttribution, person_id: int) -> ConflictError:
    """Construit l'erreur qui refuse l'attribution à `person_id` d'un identifiant détenu par l'attribution `existing` (`HELD_ELSEWHERE`)."""
    return ConflictError(
        f"Identifiant {existing.id_type}={existing.id_value!r} déjà attribué à "
        f"person_id={existing.person_id} avec statut {existing.status.value!r} ; impossible "
        f"d'attribuer à person_id={person_id}."
    )
