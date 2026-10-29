"""Attribution d'un identifiant externe à une personne, et ses changements de statut.

Le statut (`pending`, `confirmed`, `rejected`) qualifie l'attribution. Elle forme donc un agrégat distinct de `Person`, et une réattribution modifie seulement l'attribution. `Person.identifiers` en donne une copie en lecture.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

from domain.errors import IdentifierAttributionConflictError
from domain.persons.identifiers import AttributionStatus, IdentifierOrigin


class AttributionOutcome(StrEnum):
    """Issue de l'attribution d'un identifiant à une personne (`attribution_outcome`)."""

    ADDED = "added"  # identifiant absent : inséré en `pending`
    ALREADY_EXISTS = "already_exists"  # déjà attribué à cette personne
    REASSIGNED = "reassigned"  # repris d'une autre personne, chez qui il était `rejected`
    HELD_ELSEWHERE = "held_elsewhere"  # une autre personne le détient en `pending` ou `confirmed`


@dataclass(slots=True)
class IdentifierAttribution:
    """Attribution d'un identifiant externe (ORCID, idHAL, IdRef, compte HAL) à une personne. Une valeur d'identifiant appartient à une seule personne. `id_value` est sous forme canonique."""

    id: int | None
    person_id: int
    id_type: str
    id_value: str
    status: AttributionStatus = AttributionStatus.PENDING
    source: IdentifierOrigin | None = None

    def reattribute_to(self, new_person_id: int, *, source: IdentifierOrigin) -> None:
        """Déplace une attribution `rejected` vers une autre personne, en `pending`. `source` : origine de la réattribution. Lève `IdentifierAttributionConflictError` pour un autre statut."""
        if self.status is not AttributionStatus.REJECTED:
            raise IdentifierAttributionConflictError(
                f"Impossible de réattribuer l'identifiant {self.id_type}={self.id_value!r} "
                f"depuis le statut {self.status.value!r} ; seuls les identifiants rejected "
                "peuvent être réattribués.",
            )
        self.person_id = new_person_id
        self.status = AttributionStatus.PENDING
        self.source = source

    def transfer_to(self, new_person_id: int, *, source: IdentifierOrigin) -> None:
        """Déplace une attribution `pending` vers une autre personne, en `pending`. Lève `IdentifierAttributionConflictError` pour un autre statut.

        Sert à l'arbitrage automatique des conflits : la valeur revient à la personne que désigne la majorité des contributions qui la contiennent.
        """
        if self.status is not AttributionStatus.PENDING:
            raise IdentifierAttributionConflictError(
                f"Impossible de transférer l'identifiant {self.id_type}={self.id_value!r} "
                f"depuis le statut {self.status.value!r} ; seul un identifiant pending est "
                "transférable.",
            )
        self.person_id = new_person_id
        self.source = source


class AttributionResult(NamedTuple):
    """Résultat de l'attribution d'un identifiant à une personne : l'issue, la valeur normalisée, et l'attribution trouvée en base, à défaut `None`."""

    outcome: AttributionOutcome
    id_value: str
    existing: IdentifierAttribution | None


def attribution_outcome(
    existing: IdentifierAttribution | None, person_id: int
) -> AttributionOutcome:
    """Issue de l'attribution d'un identifiant à `person_id`, d'après son attribution en base (`existing`). Un identifiant détenu par une autre personne se reprend seulement après passage de son attribution à `rejected`."""
    if existing is None:
        return AttributionOutcome.ADDED
    if existing.person_id == person_id:
        return AttributionOutcome.ALREADY_EXISTS
    if existing.status is AttributionStatus.REJECTED:
        return AttributionOutcome.REASSIGNED
    return AttributionOutcome.HELD_ELSEWHERE


def held_elsewhere_conflict(
    existing: IdentifierAttribution, person_id: int
) -> IdentifierAttributionConflictError:
    """Erreur qui refuse l'attribution à `person_id` d'un identifiant que détient l'attribution `existing` (`HELD_ELSEWHERE`)."""
    return IdentifierAttributionConflictError(
        f"Identifiant {existing.id_type}={existing.id_value!r} déjà attribué à "
        f"person_id={existing.person_id} avec statut {existing.status.value!r} ; impossible "
        f"d'attribuer à person_id={person_id}.",
        id_type=existing.id_type,
        id_value=existing.id_value,
        existing_person_id=existing.person_id,
        existing_status=existing.status.value,
    )
