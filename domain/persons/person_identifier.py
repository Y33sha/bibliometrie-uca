"""Aggregate root ``PersonIdentifier`` — relation Personne ↔ identifiant
externe avec statut.

`PersonIdentifier` est un aggregate à part, pas un VO ni une entité
fille de `Person`. Justifications :

1. Le `status` (`pending` / `confirmed` / `rejected`) porte sur la
   *relation* identifier ↔ person, pas sur l'identifier nu — c'est un
   objet métier de premier rang.
2. La réattribution (déplacer un identifier d'une personne à une autre
   quand l'ancien statut était `rejected`) charge et mute l'identifier,
   pas les deux personnes — modèle aggregate-séparé qui collapse
   l'opération en un load + un save.

Identité naturelle : `(id_type, id_value)`. Identité surrogate : `id`.

`Person.identifiers: tuple[PersonIdentifier, ...]` reste possible comme
projection en lecture hydratée par le repository à la demande, mais
n'est pas la source de vérité des mutations.

La logique métier touchant aux attributions d'identifiants (transitions
de statut, réattribution) vit ici.
"""

from dataclasses import dataclass

from domain.errors import CannotReattributeError
from domain.persons.identifiers import AttributionStatus


@dataclass(slots=True)
class PersonIdentifier:
    """Attribution d'un identifiant externe (ORCID, idHAL, IdRef,
    hal_person_id) à une personne, avec statut.

    `id_type` ∈ ``PERSON_IDENTIFIER_TYPES``. `id_value` est la valeur
    canonique stockée en base (déjà normalisée par les VOs ORCID/IdHAL/
    IdRef à la construction ; `hal_person_id` est stocké tel quel).
    """

    id: int | None
    person_id: int
    id_type: str
    id_value: str
    status: AttributionStatus = AttributionStatus.PENDING
    source: str | None = None

    def confirm(self) -> None:
        """Marque l'attribution comme validée par l'utilisateur."""
        self.status = AttributionStatus.CONFIRMED

    def reject(self) -> None:
        """Marque l'attribution comme rejetée par l'utilisateur."""
        self.status = AttributionStatus.REJECTED

    def reattribute_to(self, new_person_id: int, *, source: str) -> None:
        """Déplace l'attribution vers une autre personne.

        Autorisée uniquement depuis le statut `REJECTED` : un identifiant
        rejeté pour une personne A peut être réattribué à une personne B
        avec statut `PENDING`. Lève `CannotReattributeError` sinon.

        `source` trace l'origine de la réattribution (ex. "manual",
        "matching_cascade").
        """
        if self.status is not AttributionStatus.REJECTED:
            raise CannotReattributeError(
                f"Impossible de réattribuer l'identifiant {self.id_type}={self.id_value!r} "
                f"depuis le statut {self.status.value!r} ; seuls les identifiants rejected "
                "peuvent être réattribués.",
            )
        self.person_id = new_person_id
        self.status = AttributionStatus.PENDING
        self.source = source
