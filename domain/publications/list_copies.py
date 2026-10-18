"""Doublons d'auteur dans la liste d'une notice : la source répète tout ou partie de la liste à sa suite (A B C A B C), ou chaque nom à sa place (A A B B…)."""

from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise

from domain.publications.author_grouping import Signature

# Nombre de noms complets répétés au même décalage qui signale la répétition d'un bloc de la liste.
MIN_COPIED_NAMES = 2
# Nombre de paires côte à côte, de noms différents et à la suite, qui signale une liste où chaque nom est répété à sa place.
MIN_DOUBLED_PAIRS = 4

type Name = tuple[str, str]


def copied_signatures(signatures: Sequence[Signature]) -> dict[int, int]:
    """Doublons d'auteur d'une notice, chacun vers la première occurrence de son nom complet."""
    ordered = sorted((s for s in signatures if s.last_name), key=lambda s: (s.position, s.id))
    by_name: dict[Name, list[Signature]] = defaultdict(list)
    for s in ordered:
        by_name[_name(s)].append(s)
    copies = _block_copies(by_name) | _doubled_in_place(ordered)
    return {s.id: by_name[_name(s)][0].id for s in ordered if s.id in copies}


def _block_copies(by_name: dict[Name, list[Signature]]) -> set[int]:
    """Occurrences qui suivent la précédente du même nom d'un décalage de répétition.

    Le décalage de répétition est supérieur à 1 et commun à au moins `MIN_COPIED_NAMES` noms. Les homonymes d'une liste alphabétique sont côte à côte, au décalage 1.
    """
    names_by_offset: dict[int, set[Name]] = defaultdict(set)
    for name, occurrences in by_name.items():
        for a, b in pairwise(occurrences):
            if b.position - a.position > 1:
                names_by_offset[b.position - a.position].add(name)
    offsets = {d for d, names in names_by_offset.items() if len(names) >= MIN_COPIED_NAMES}
    return {
        b.id
        for occurrences in by_name.values()
        for a, b in pairwise(occurrences)
        if b.position - a.position in offsets
    }


def _doubled_in_place(ordered: Sequence[Signature]) -> set[int]:
    """Secondes occurrences des suites d'au moins `MIN_DOUBLED_PAIRS` paires côte à côte (A A B B…), de noms différents."""
    copies: set[int] = set()
    run: list[Signature] = []

    def close() -> None:
        if len(run) >= MIN_DOUBLED_PAIRS:
            copies.update(s.id for s in run)
        run.clear()

    i = 0
    while i + 1 < len(ordered):
        a, b = ordered[i], ordered[i + 1]
        if b.position == a.position + 1 and _name(a) == _name(b):
            if run and (run[-1].position != a.position - 1 or _name(run[-1]) == _name(a)):
                close()
            run.append(b)
            i += 2
        else:
            close()
            i += 1
    close()
    return copies


def _name(s: Signature) -> Name:
    return (s.last_name, s.first_name)
