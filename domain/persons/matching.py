"""Règles pures de matching d'authorships à des personnes.

Module pensé pour accueillir progressivement la cascade contractuelle
de matching (compte HAL → cross-source → IdRef/ORCID → name forms),
aujourd'hui dispersée dans
``application/pipeline/persons/create_persons_from_source_authorships.py``.
On commence par la brique la plus simple : la résolution d'un
identifiant unique vers une ``person_id``.
"""

from collections.abc import Mapping


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
