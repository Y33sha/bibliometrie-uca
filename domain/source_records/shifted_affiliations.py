"""Affiliations décalées d'OpenAlex : détection et correction.

Dans certains enregistrements sources OpenAlex, la liste des auteurs et celle des affiliations sont décalées d'un rang à partir d'une position. Chaque auteur reçoit alors son affiliation et celle d'un voisin. Un auteur inséré, le plus souvent un auteur collectif, reçoit l'affiliation du suivant, et chaque auteur après lui reçoit la sienne et celle du suivant. Un auteur manquant donne à chaque auteur la sienne et celle du précédent.

Les affiliations se comparent normalisées (`normalize_text`) : une même affiliation figure chez deux auteurs voisins avec ou sans virgules.
"""

from collections.abc import Sequence

from domain.normalize import normalize_text

MIN_LINKS = 3
"""Nombre minimal de chaînons d'un enregistrement source décalé."""

MIN_LINK_SHARE = 0.4
"""Part minimale des chaînons parmi les auteurs intérieurs d'un enregistrement source décalé."""


def _keys(affiliations: Sequence[str]) -> frozenset[str]:
    return frozenset(key for affiliation in affiliations if (key := normalize_text(affiliation)))


def _shifted_run(keys: Sequence[frozenset[str]]) -> tuple[int, int] | None:
    """Renvoie les positions du premier et du dernier auteur de la suite décalée : de l'auteur avant le premier chaînon à l'auteur après le dernier. `None` avec trop peu de chaînons (`MIN_LINKS`, `MIN_LINK_SHARE`).

    Un auteur intérieur, entre deux voisins à affiliation, forme un chaînon quand il partage une affiliation avec le précédent et une autre, différente, avec le suivant : A B, B C, C D. Dans une équipe, l'affiliation partagée est la même des deux côtés.
    """
    links: list[int] = []
    interior = 0
    for position in range(1, len(keys) - 1):
        before, here, after = keys[position - 1], keys[position], keys[position + 1]
        if not (before and here and after):
            continue
        interior += 1
        left, right = here & before, here & after
        if left and right and not left & right:
            links.append(position)
    if len(links) < MIN_LINKS or len(links) < MIN_LINK_SHARE * interior:
        return None
    return links[0] - 1, links[-1] + 1


def unshifted_affiliations(
    affiliations: Sequence[Sequence[str]], collective: Sequence[bool]
) -> list[list[str]] | None:
    """Renvoie, pour un enregistrement source décalé, les affiliations gardées par chaque auteur. `None` pour un enregistrement source sans décalage.

    Avec un auteur collectif, un auteur est inséré : chaque auteur de la suite décalée garde l'affiliation partagée avec le précédent. Sans auteur collectif, un auteur manque : chaque auteur garde l'affiliation partagée avec le suivant. Sans voisin de ce côté dans la suite, ou sans affiliation partagée avec lui, un auteur garde ses affiliations moins celles de l'autre voisin. Un auteur collectif perd alors ses affiliations. Les auteurs hors de la suite gardent leurs affiliations. Chaque auteur garde ses affiliations dans leur écriture d'origine.

    Args:
        affiliations: affiliations brutes de chaque auteur, dans l'ordre des auteurs.
        collective: auteurs collectifs, dans le même ordre.
    """
    keys = [_keys(a) for a in affiliations]
    run = _shifted_run(keys)
    if run is None:
        return None
    start, end = run
    step = -1 if any(collective) else 1
    kept = list(keys)
    for position in range(start, end + 1):
        here = keys[position]
        if not here:
            continue
        toward, away = position + step, position - step
        shared = here & keys[toward] if start <= toward <= end else frozenset()
        if shared:
            kept[position] = shared
        elif collective[position]:
            kept[position] = frozenset()
        else:
            other = keys[away] if 0 <= away < len(keys) else frozenset()
            kept[position] = (here - other) or here
    return [
        [a for a in strings if normalize_text(a) in kept[position]]
        for position, strings in enumerate(affiliations)
    ]
