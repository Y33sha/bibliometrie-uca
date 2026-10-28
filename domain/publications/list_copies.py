"""Doublons d'auteur dans la liste d'un enregistrement source : la source répète tout ou partie de la liste à sa suite (A B C A B C), chaque nom à sa place (A A B B…), ou les auteurs dans un autre ordre, en liste des membres d'un collectif (A B C D B X A)."""

from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise

from domain.publications.author_grouping import SourceContribution

# Nombre de noms complets répétés qui signale une copie : au même décalage pour un bloc de la liste, à des décalages quelconques pour une liste de membres.
MIN_COPIED_NAMES = 2
# Part des auteurs de la liste répétés à distance qui signale une liste de membres.
MIN_MEMBER_LIST_SHARE = 0.10
# Nombre de paires côte à côte, de noms différents et à la suite, qui signale une liste où chaque nom est répété à sa place.
MIN_DOUBLED_PAIRS = 4

type Name = tuple[str, str]
# Rang d'une contribution source dans la liste des auteurs, et la contribution source.
type Placed = tuple[int, SourceContribution]


def copied_source_contributions(
    source_contributions: Sequence[SourceContribution],
) -> dict[int, int]:
    """Doublons d'auteur d'un enregistrement source, chacun vers la première occurrence de son nom complet. Seules les contributions sources qui ont une position et un nom de famille comptent."""
    ordered = sorted(
        ((s.position, s) for s in source_contributions if s.last_name and s.position is not None),
        key=lambda p: (p[0], p[1].id),
    )
    by_name: dict[Name, list[Placed]] = defaultdict(list)
    for p in ordered:
        by_name[_name(p)].append(p)
    copies = (
        _block_copies(by_name)
        | _doubled_in_place(ordered)
        | _member_list_copies(by_name, len(ordered))
    )
    return {s.id: by_name[_name(p)][0][1].id for p in ordered if (s := p[1]).id in copies}


def _block_copies(by_name: dict[Name, list[Placed]]) -> set[int]:
    """Occurrences qui suivent la précédente du même nom d'un décalage de répétition.

    Le décalage de répétition est supérieur à 1 et commun à au moins `MIN_COPIED_NAMES` noms. Les homonymes d'une liste alphabétique sont côte à côte, au décalage 1.
    """
    names_by_offset: dict[int, set[Name]] = defaultdict(set)
    for name, occurrences in by_name.items():
        for (pa, _), (pb, _) in pairwise(occurrences):
            if pb - pa > 1:
                names_by_offset[pb - pa].add(name)
    offsets = {d for d, names in names_by_offset.items() if len(names) >= MIN_COPIED_NAMES}
    return {
        b.id
        for occurrences in by_name.values()
        for (pa, _), (pb, b) in pairwise(occurrences)
        if pb - pa in offsets
    }


def _member_list_copies(by_name: dict[Name, list[Placed]], list_size: int) -> set[int]:
    """Occurrences qui suivent la précédente du même nom à distance (décalage supérieur à 1), quand au moins `MIN_COPIED_NAMES` noms et `MIN_MEMBER_LIST_SHARE` des `list_size` auteurs se répètent à distance.

    La liste des membres d'un collectif reprend des auteurs dans un autre ordre : chaque nom repris a son propre décalage. Les homonymes sont côte à côte, ou moins nombreux.
    """
    distant = {
        name: [b.id for (pa, _), (pb, b) in pairwise(occurrences) if pb - pa > 1]
        for name, occurrences in by_name.items()
    }
    repeated = [ids for ids in distant.values() if ids]
    if len(repeated) < max(MIN_COPIED_NAMES, MIN_MEMBER_LIST_SHARE * list_size):
        return set()
    return {i for ids in repeated for i in ids}


def _doubled_in_place(ordered: Sequence[Placed]) -> set[int]:
    """Secondes occurrences des suites d'au moins `MIN_DOUBLED_PAIRS` paires côte à côte (A A B B…), de noms différents."""
    copies: set[int] = set()
    run: list[Placed] = []

    def close() -> None:
        if len(run) >= MIN_DOUBLED_PAIRS:
            copies.update(s.id for _, s in run)
        run.clear()

    i = 0
    while i + 1 < len(ordered):
        a, b = ordered[i], ordered[i + 1]
        if b[0] == a[0] + 1 and _name(a) == _name(b):
            if run and (run[-1][0] != a[0] - 1 or _name(run[-1]) == _name(a)):
                close()
            run.append(b)
            i += 2
        else:
            close()
            i += 1
    close()
    return copies


def _name(p: Placed) -> Name:
    return (p[1].last_name, p[1].first_name)
