"""Aggregate root `Person` — référentiel chercheur unifié multi-sources.

Une `Person` rassemble sous une identité unique les signatures d'auteur qu'un même chercheur porte à travers les sources (HAL, OpenAlex, WoS, …). Identité = `id` (clé surrogate).

Composition / associations :
- `identifiers: tuple[IdentifierAttribution, ...]` — projection lecture (chaque `IdentifierAttribution` est un aggregate séparé).
- `name_forms: tuple[PersonNameForm, ...]` — formes textuelles connues (VOs).

`hal_person_id` est un `IdentifierAttribution` d'`id_type` = `"hal_person_id"`.

La logique métier touchant à une personne (fusion, matching cross-source, création contrôlée, normalisation des noms) vit ici.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from domain.errors import ValidationError
from domain.persons.identifier_attribution import IdentifierAttribution
from domain.persons.name_forms import PersonNameForm


def validated_name(last_name: str, first_name: str) -> tuple[str, str]:
    """Nom et prénom débarrassés de leurs espaces de bord. Lève `ValidationError` sans patronyme : c'est de lui que dérivent les formes qui rendent une personne matchable."""
    last_name, first_name = last_name.strip(), first_name.strip()
    if not last_name:
        raise ValidationError("Le nom est requis")
    return last_name, first_name


class PersonExclusion(StrEnum):
    """Motif d'exclusion d'une personne, décidé à la main. Une personne exclue est absente de l'UI publique et du périmètre ; ses formes de nom restent des ancres du matching."""

    # Fausse entité : nom d'équipe, plusieurs noms dans un même champ…
    NOT_A_PERSON = "not_a_person"
    # Personne réelle, rattachée au périmètre par erreur.
    OUT_OF_PERIMETER = "out_of_perimeter"


@dataclass(slots=True)
class Person:
    """Référentiel chercheur unifié (aggregate root)."""

    id: int | None
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    exclusion: PersonExclusion | None = None
    identifiers: tuple[IdentifierAttribution, ...] = field(default=())
    name_forms: tuple[PersonNameForm, ...] = field(default=())
