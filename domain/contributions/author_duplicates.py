"""Doublons d'auteur dans la liste d'un enregistrement source.

Avant l'alignement, la liste seule les révèle : la source répète tout ou partie de la liste à sa suite (A B C A B C), chaque nom à sa place (A A B B…), ou les auteurs dans un autre ordre, en liste des membres d'un collectif (A B C D B X A). Après l'alignement, un nom répété une fois se révèle par sa contribution restée seule (`unaligned_duplicates`).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise

from domain.contributions.author_grouping import Contribution, SourceContribution
from domain.persons.name_matching import is_full_first_name

MIN_DUPLICATED_NAMES = 2
"""Nombre de noms complets répétés qui signale des doublons : au même décalage pour un bloc de la liste, à des décalages quelconques pour une liste de membres."""
MIN_MEMBER_LIST_SHARE = 0.10
"""Part des auteurs de la liste répétés à distance qui signale une liste de membres."""
MIN_DOUBLED_PAIRS = 4
"""Nombre de paires côte à côte, de noms différents et à la suite, qui signale une liste où chaque nom est répété à sa place."""

type Name = tuple[str, str]
# Rang d'une contribution source dans la liste des auteurs, et la contribution source.
type Placed = tuple[int, SourceContribution]


def duplicate_source_contributions(
    source_contributions: Sequence[SourceContribution],
) -> dict[int, int]:
    """Renvoie les doublons d'auteur d'un enregistrement source, chacun vers la première occurrence de son nom complet. Seules les contributions sources qui ont une position et un nom de famille comptent."""
    ordered = sorted(
        ((s.position, s) for s in source_contributions if s.last_name and s.position is not None),
        key=lambda p: (p[0], p[1].id),
    )
    by_name: dict[Name, list[Placed]] = defaultdict(list)
    for p in ordered:
        by_name[_name(p)].append(p)
    duplicates = (
        _block_duplicates(by_name)
        | _doubled_in_place(ordered)
        | _member_list_duplicates(by_name, len(ordered))
    )
    return {s.id: by_name[_name(p)][0][1].id for p in ordered if (s := p[1]).id in duplicates}


def unaligned_duplicates(
    contributions: Sequence[Contribution], source_contributions: Mapping[int, SourceContribution]
) -> dict[int, int]:
    """Renvoie les doublons d'auteur révélés par l'alignement, chacun vers sa jumelle.

    Un doublon est seul dans sa contribution. Sa jumelle appartient au même enregistrement source, a le même nom de famille et le même prénom complet, et s'aligne avec d'autres enregistrements sources. Un prénom réduit à des initiales ne suffit pas : « wang / z » désigne souvent deux auteurs voisins dans l'ordre alphabétique.

    Args:
        source_contributions: contributions sources alignées, par identifiant.
    """
    aligned: dict[tuple[int, str, str], int] = {}
    for g in contributions:
        if len(g.members) > 1:
            for m in g.members:
                s = source_contributions[m.source_contribution]
                aligned.setdefault((s.source_record, s.last_name, s.first_name), s.id)
    duplicates: dict[int, int] = {}
    for g in contributions:
        if len(g.members) == 1:
            s = source_contributions[g.members[0].source_contribution]
            twin = aligned.get((s.source_record, s.last_name, s.first_name))
            if twin is not None and s.last_name and is_full_first_name(s.first_name):
                duplicates[s.id] = twin
    return duplicates


def _block_duplicates(by_name: dict[Name, list[Placed]]) -> set[int]:
    """Renvoie les occurrences qui suivent la précédente du même nom d'un décalage de répétition.

    Le décalage de répétition est supérieur à 1 et commun à au moins `MIN_DUPLICATED_NAMES` noms. Les homonymes d'une liste alphabétique sont côte à côte, au décalage 1.
    """
    names_by_offset: dict[int, set[Name]] = defaultdict(set)
    for name, occurrences in by_name.items():
        for (pa, _), (pb, _) in pairwise(occurrences):
            if pb - pa > 1:
                names_by_offset[pb - pa].add(name)
    offsets = {d for d, names in names_by_offset.items() if len(names) >= MIN_DUPLICATED_NAMES}
    return {
        b.id
        for occurrences in by_name.values()
        for (pa, _), (pb, b) in pairwise(occurrences)
        if pb - pa in offsets
    }


def _member_list_duplicates(by_name: dict[Name, list[Placed]], list_size: int) -> set[int]:
    """Renvoie les occurrences qui suivent la précédente du même nom à distance (décalage supérieur à 1), quand au moins `MIN_DUPLICATED_NAMES` noms et `MIN_MEMBER_LIST_SHARE` des `list_size` auteurs se répètent à distance.

    La liste des membres d'un collectif reprend des auteurs dans un autre ordre : chaque nom repris a son propre décalage. Les homonymes sont côte à côte, ou moins nombreux.
    """
    distant = {
        name: [b.id for (pa, _), (pb, b) in pairwise(occurrences) if pb - pa > 1]
        for name, occurrences in by_name.items()
    }
    repeated = [ids for ids in distant.values() if ids]
    if len(repeated) < max(MIN_DUPLICATED_NAMES, MIN_MEMBER_LIST_SHARE * list_size):
        return set()
    return {i for ids in repeated for i in ids}


def _doubled_in_place(ordered: Sequence[Placed]) -> set[int]:
    """Renvoie les secondes occurrences des suites d'au moins `MIN_DOUBLED_PAIRS` paires côte à côte (A A B B…), de noms différents."""
    duplicates: set[int] = set()
    run: list[Placed] = []

    def close() -> None:
        if len(run) >= MIN_DOUBLED_PAIRS:
            duplicates.update(s.id for _, s in run)
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
    return duplicates


def _name(p: Placed) -> Name:
    return (p[1].last_name, p[1].first_name)
