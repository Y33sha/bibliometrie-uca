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


def is_shifted(keys: Sequence[frozenset[str]]) -> bool:
    """Vrai quand les affiliations normalisées de chaque auteur, dans l'ordre des auteurs, forment assez de chaînons (`MIN_LINKS`, `MIN_LINK_SHARE`).

    Un auteur intérieur, entre deux voisins à affiliation, forme un chaînon quand il partage une affiliation avec le précédent et une autre, différente, avec le suivant : A B, B C, C D. Dans une équipe, l'affiliation partagée est la même des deux côtés.
    """
    links = interior = 0
    for position in range(1, len(keys) - 1):
        before, here, after = keys[position - 1], keys[position], keys[position + 1]
        if not (before and here and after):
            continue
        interior += 1
        left, right = here & before, here & after
        links += bool(left and right and not left & right)
    return links >= MIN_LINKS and links >= MIN_LINK_SHARE * interior


def _carried(keys: Sequence[frozenset[str]], start: int) -> list[frozenset[str]]:
    """Renvoie l'affiliation reportée par chaque auteur à partir de `start` : celle de `start` entière, puis pour chaque auteur ses affiliations moins celle reportée par le précédent, à défaut celle reportée par le précédent. Un auteur sans affiliation reporte une affiliation vide, et la chaîne repart à l'auteur suivant."""
    carried = [frozenset[str]() for _ in keys]
    previous: frozenset[str] | None = None
    for position in range(start, len(keys)):
        here = keys[position]
        if not here:
            previous = None
            continue
        current = here if previous is None else (here - previous) or previous
        carried[position] = current
        previous = current
    return carried


def unshifted_affiliations(
    affiliations: Sequence[Sequence[str]], collective: Sequence[bool]
) -> list[list[str]] | None:
    """Renvoie, pour un enregistrement source décalé (`is_shifted`), les affiliations gardées par chaque auteur. `None` pour un enregistrement source sans décalage.

    Avec un auteur collectif, le premier est l'auteur inséré. Les auteurs avant lui gardent leurs affiliations. Il n'en garde aucune. Chaque auteur après lui garde l'affiliation reportée par le précédent ; après un auteur sans affiliation, il garde les siennes. Sans auteur collectif, un auteur manque : chaque auteur garde l'affiliation qu'il reporte depuis le premier auteur. Chaque auteur garde ses affiliations dans leur écriture d'origine.

    Args:
        affiliations: affiliations brutes de chaque auteur, dans l'ordre des auteurs.
        collective: auteurs collectifs, dans le même ordre.
    """
    keys = [_keys(a) for a in affiliations]
    if not is_shifted(keys):
        return None
    inserted = next(
        (position for position, is_collective in enumerate(collective) if is_collective), None
    )
    if inserted is None:
        kept = _carried(keys, 0)
    else:
        carried = _carried(keys, inserted)
        kept = [
            keys[position]
            if position < inserted
            else frozenset()
            if position == inserted
            else carried[position - 1] or keys[position]
            for position in range(len(keys))
        ]
    return [
        [a for a in strings if normalize_text(a) in kept[position]]
        for position, strings in enumerate(affiliations)
    ]
