"""Aggregate root `Person` — référentiel chercheur unifié multi-sources.

Une `Person` rassemble sous une identité unique les signatures d'auteur qu'un même chercheur porte à travers les sources (HAL, OpenAlex, WoS, …). Identité = `id` (clé surrogate).

Composition / associations :
- `identifiers: tuple[PersonIdentifier, ...]` — projection lecture (chaque `PersonIdentifier` est un aggregate séparé).
- `name_forms: tuple[PersonNameForm, ...]` — formes textuelles connues (VOs).

`hal_person_id` n'est pas un attribut nu : c'est un `PersonIdentifier` d'`id_type` = `"hal_person_id"`. Jamais exposé en UI.

La logique métier touchant à une personne (fusion, matching cross-source, création contrôlée, normalisation des noms) vit ici.
"""

from dataclasses import dataclass, field

from domain.errors import ConflictError
from domain.persons.name_forms import PersonNameForm
from domain.persons.person_identifier import PersonIdentifier


@dataclass(slots=True)
class Person:
    """Référentiel chercheur unifié (aggregate root)."""

    id: int | None
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    rejected: bool = False
    identifiers: tuple[PersonIdentifier, ...] = field(default=())
    name_forms: tuple[PersonNameForm, ...] = field(default=())

    def can_merge_with(self, other: "Person", *, has_distinct_rh: bool) -> None:
        """Valide qu'une fusion `self ← other` est autorisée.

        Invariant : refus si les deux personnes ont chacune une fiche RH distincte (risque de perdre de l'information RH). L'appelant fournit l'information `has_distinct_rh`, typiquement déterminée par le repository en interrogeant `persons_rh`.

        Lève `ConflictError` si l'invariant est violé.
        """
        if has_distinct_rh:
            raise ConflictError(
                f"REFUS de fusion : les personnes #{self.id} et #{other.id} "
                "ont chacune une fiche RH distincte.",
            )
