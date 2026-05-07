"""Règles pures de matching d'authorships à des personnes.

Module pensé pour accueillir progressivement la cascade contractuelle
de matching (compte HAL → cross-source → IdRef/ORCID → name forms),
aujourd'hui dispersée dans
``application/pipeline/persons/create_persons_from_source_authorships.py``.
On commence par la brique la plus simple : la résolution d'un
identifiant unique vers une ``person_id``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class NameFormDecision:
    """Décision résultant du lookup d'une authorship dans
    ``person_name_forms``.

    Trois actions possibles : ``match`` (rattacher à une personne
    existante), ``create`` (créer une nouvelle personne), ``skip`` (ne
    rien faire — soit ambiguïté de nom, soit création interdite par
    `allow_create`). Le ``reason`` n'est rempli que pour ``skip`` à des
    fins de logs/stats.
    """

    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: str = ""


def decide_name_form_outcome(
    person_ids: list[int] | None,
    allow_create: bool,
) -> NameFormDecision:
    """Arbitre la décision de matching après lookup dans
    ``person_name_forms``.

    Cascade :

    - 1 ``person_id`` → ``match`` (rattachement direct).
    - N ``person_ids`` → ``skip`` avec ``reason="ambiguous_name_form"``
      (homonymes en BDD, on laisse le traitement manuel trancher).
    - 0 ``person_ids`` (forme inconnue) + ``allow_create`` → ``create``.
    - 0 ``person_ids`` + pas ``allow_create`` → ``skip`` avec
      ``reason="creation_not_allowed"`` (typiquement les rôles
      non-auteur des thèses, cf.
      ``domain.persons.creation.allow_person_creation``).
    """
    if person_ids is None:
        if allow_create:
            return NameFormDecision(action="create")
        return NameFormDecision(action="skip", reason="creation_not_allowed")
    if len(person_ids) == 1:
        return NameFormDecision(action="match", person_id=person_ids[0])
    return NameFormDecision(action="skip", reason="ambiguous_name_form")


def decide_match_by_identifier(
    value: str | None,
    identifier_map: Mapping[str, int],
) -> int | None:
    """Résout un identifiant (IdRef, ORCID…) vers une ``person_id``.

    Retourne le ``person_id`` si ``value`` est présent dans
    ``identifier_map``, ``None`` sinon (y compris si ``value`` est
    falsy).

    ``identifier_map`` est typiquement ``{idref: person_id}`` ou
    ``{orcid: person_id}`` prefetché via une query du type
    ``fetch_idref_to_person_map`` / ``fetch_orcid_to_person_map``,
    déjà filtré sur les statuts non-``rejected``. La fonction n'a
    donc pas à reconnaître la nature de l'identifiant : elle est
    générique et marche pour n'importe quel id_type indexé sur
    ``person_identifiers``.
    """
    if not value:
        return None
    return identifier_map.get(value)
