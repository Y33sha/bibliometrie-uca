"""Aggregate root `IdentifierAttribution` — relation Personne ↔ identifiant externe avec statut.

Aggregate à part (pas un VO, pas une entité fille de `Person`) : le `status` (`pending` / `confirmed` / `rejected`) porte sur la *relation* identifier ↔ person, et la réattribution charge et mute le seul identifier (load + save), pas les deux personnes. Clé naturelle : `(id_type, id_value)` ; clé surrogate : `id`.

`Person.identifiers: tuple[IdentifierAttribution, ...]` est une projection en lecture hydratée par le repository à la demande, pas la source de vérité des mutations.

La logique métier touchant aux attributions d'identifiants (transitions de statut, réattribution) vit ici.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

from domain.errors import CannotAttributeConflict
from domain.persons.identifiers import AttributionStatus, IdentifierOrigin


class AttributionOutcome(StrEnum):
    """Issue de l'attribution d'un identifiant à une personne (`attribution_outcome`)."""

    ADDED = "added"  # identifiant absent : inséré en `pending`
    ALREADY_EXISTS = "already_exists"  # déjà attribué à cette personne
    REASSIGNED = "reassigned"  # repris d'une autre personne, chez qui il était `rejected`
    HELD_ELSEWHERE = "held_elsewhere"  # une autre personne le détient en `pending` ou `confirmed`


@dataclass(slots=True)
class IdentifierAttribution:
    """Attribution d'un identifiant externe (ORCID, idHAL, IdRef, hal_person_id) à une personne, avec statut.

    `id_type` ∈ `PERSON_IDENTIFIER_TYPES`. `id_value` est la valeur canonique stockée en base, normalisée par le value object de son type (`normalized_identifier_value`).
    """

    id: int | None
    person_id: int
    id_type: str
    id_value: str
    status: AttributionStatus = AttributionStatus.PENDING
    source: IdentifierOrigin | None = None

    def reattribute_to(self, new_person_id: int, *, source: IdentifierOrigin) -> None:
        """Déplace l'attribution vers une autre personne.

        Autorisée uniquement depuis le statut `REJECTED` : un identifiant rejeté pour une personne A peut être réattribué à une personne B avec statut `PENDING`. Lève `CannotAttributeConflict` sinon.

        `source` trace l'origine de la réattribution (`IdentifierOrigin`).
        """
        if self.status is not AttributionStatus.REJECTED:
            raise CannotAttributeConflict(
                f"Impossible de réattribuer l'identifiant {self.id_type}={self.id_value!r} "
                f"depuis le statut {self.status.value!r} ; seuls les identifiants rejected "
                "peuvent être réattribués.",
            )
        self.person_id = new_person_id
        self.status = AttributionStatus.PENDING
        self.source = source

    def transfer_to(self, new_person_id: int, *, source: IdentifierOrigin) -> None:
        """Transfère une attribution `pending` vers une autre personne.

        Réservé à l'arbitrage automatique des conflits d'attribution : une valeur `pending` est déplacée vers la personne que désigne la majorité des groupes qui la portent. Le statut reste `pending` (attribution non vérifiée, simplement mieux placée).

        Interdit sur `confirmed` (attribution verrouillée par l'admin — jamais déplacée automatiquement) et sur `rejected` (qui relève de `reattribute_to`). Lève `CannotAttributeConflict` sinon.
        """
        if self.status is not AttributionStatus.PENDING:
            raise CannotAttributeConflict(
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
    """Issue de l'attribution à `person_id` d'un identifiant dont `existing` est l'attribution en base.

    Une autre personne qui détient l'identifiant en `pending` ou `confirmed` le garde (`HELD_ELSEWHERE`). Pour le lui reprendre, son statut doit d'abord passer à `rejected`.
    """
    if existing is None:
        return AttributionOutcome.ADDED
    if existing.person_id == person_id:
        return AttributionOutcome.ALREADY_EXISTS
    if existing.status is AttributionStatus.REJECTED:
        return AttributionOutcome.REASSIGNED
    return AttributionOutcome.HELD_ELSEWHERE


def held_elsewhere_conflict(
    existing: IdentifierAttribution, person_id: int
) -> CannotAttributeConflict:
    """Erreur qui refuse l'attribution à `person_id` d'un identifiant que détient l'attribution `existing` (`HELD_ELSEWHERE`)."""
    return CannotAttributeConflict(
        f"Identifiant {existing.id_type}={existing.id_value!r} déjà attribué à "
        f"person_id={existing.person_id} avec statut {existing.status.value!r} ; impossible "
        f"d'attribuer à person_id={person_id}.",
        id_type=existing.id_type,
        id_value=existing.id_value,
        existing_person_id=existing.person_id,
        existing_status=existing.status.value,
    )
