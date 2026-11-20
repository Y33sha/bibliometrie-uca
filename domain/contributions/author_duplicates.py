"""Doublons d'auteur dans la liste d'un enregistrement source.

Avant l'alignement, la liste seule les révèle : la source répète tout ou partie de la liste à sa suite (A B C A B C), chaque nom à sa place (A A B B…), ou les auteurs dans un autre ordre, en liste des membres d'un collectif (A B C D B X A). La comparaison avec les autres listes de la publication révèle un nom répété sous deux graphies (`cross_list_duplicates`). Après l'alignement, un nom répété une fois se révèle par sa contribution restée seule (`unaligned_duplicates`).
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from functools import lru_cache
from itertools import chain, pairwise

from domain.contributions.author_grouping import (
    LARGE_LIST_AUTHORS,
    Contribution,
    SourceContribution,
)
from domain.persons.name_matching import is_full_first_name, names_compatible
from domain.sources.registry import Source

MIN_DUPLICATED_NAMES = 2
"""Nombre de noms complets répétés qui signale des doublons : au même décalage pour un bloc de la liste, à des décalages quelconques pour une liste de membres."""
MIN_MEMBER_LIST_SHARE = 0.10
"""Part des auteurs de la liste répétés à distance qui signale une liste de membres."""
MIN_DOUBLED_PAIRS = 4
"""Nombre de paires côte à côte, de noms différents et à la suite, qui signale une liste où chaque nom est répété à sa place."""
SOURCES_MERGING_HOMONYMS: frozenset[str] = frozenset({Source.WOS})
"""Sources qui fusionnent des homonymes de la liste d'auteurs. Leur liste ne prouve pas un doublon (`cross_list_duplicates`)."""
SOURCES_WITH_AUTHOR_ORCID: frozenset[str] = frozenset({Source.HAL, Source.INSPIRE})
"""Sources dont l'ORCID désigne l'auteur de la contribution source, même répété dans la liste : compte de l'auteur chez HAL, listes vérifiées chez INSPIRE. Crossref, OpenAlex et DataCite donnent un même ORCID à des homonymes voisins."""
MAX_GAP_IN_LARGE_LIST = 10
"""Écart maximal de rang entre les deux inscriptions d'un auteur dans la liste alphabétique d'une grande collaboration, comptée dans l'ordre de la liste. D'autres noms s'intercalent entre deux graphies voisines (« porteboeuf », « porteboeuf houssais »)."""

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


def cross_list_duplicates(
    source_records: Mapping[int, Sequence[SourceContribution]], references: Collection[int]
) -> dict[int, int]:
    """Renvoie les doublons d'auteur révélés par les listes de la publication, chacun vers l'occurrence précédente de son nom.

    Dans la liste d'un enregistrement source, deux contributions sources au nom d'un même auteur (`_same_author`) forment un doublon :

    - quand elles ont le même ORCID d'auteur (`SourceContribution.author_orcid`) ;
    - dans une grande collaboration (`LARGE_LIST_AUTHORS`), quand elles sont voisines (`MAX_GAP_IN_LARGE_LIST`), qu'un nom de famille prolonge l'autre (`_extended_last_name`) et qu'une liste de référence cite le nom une seule fois ;
    - sinon, quand une liste de référence cite le nom une seule fois, quand l'une a un prénom complet et l'autre des initiales (deux listes mises bout à bout), ou quand elles ont le même nom et le même prénom complet, dans cet ordre ou permutés.

    Hors ORCID commun, deux ORCID non neutralisés différents pour ce nom, dans les listes de la publication, désignent deux homonymes.

    Args:
        source_records: contributions sources de chaque enregistrement source.
        references: enregistrements sources dont la liste prouve un doublon.
    """
    lists = {
        record: sorted(
            (s for s in contributions if s.last_name and s.position is not None),
            key=lambda s: (s.position, s.id),
        )
        for record, contributions in source_records.items()
    }
    built: dict[int, WordIndex] = {}

    def index_of(record: int) -> WordIndex:
        if record not in built:
            built[record] = _word_index(lists[record])
        return built[record]

    duplicates: dict[int, int] = {}
    for record, ordered in lists.items():
        others = [o for o in references if o != record and o in lists]
        large = len(ordered) >= LARGE_LIST_AUTHORS
        pairs = (
            _neighbour_pairs(ordered) if large else _same_author_pairs(ordered, index_of(record))
        )
        candidates = chain(
            ((a, b, True) for a, b in _same_orcid_pairs(ordered)),
            ((a, b, False) for a, b in pairs),
        )
        for a, b, same_orcid in candidates:
            if a.id in duplicates or b.id in duplicates:
                continue
            single = [
                (cited[0], len(lists[o]))
                for o in others
                if len(cited := _namesakes(a, b, index_of(o))) == 1
            ]
            if same_orcid or (
                (single or (not large and _repeated_in_small_list(a, b)))
                and len(_orcids(a, b, map(index_of, lists))) <= 1
            ):
                kept, repeated = _kept_occurrence(a, b, len(ordered), single)
                duplicates[repeated.id] = kept.id
    return duplicates


def _same_orcid_pairs(
    ordered: Sequence[SourceContribution],
) -> Iterator[tuple[SourceContribution, SourceContribution]]:
    """Renvoie les paires de contributions sources de la liste au nom d'un même auteur (`_same_author`) et au même ORCID d'auteur, dans l'ordre de la liste."""
    by_orcid: dict[str, list[SourceContribution]] = defaultdict(list)
    for s in ordered:
        if s.author_orcid:
            by_orcid[s.author_orcid].append(s)
    for occurrences in by_orcid.values():
        if len(occurrences) > 1:
            yield from _same_author_pairs(occurrences, _word_index(occurrences))


def _kept_occurrence(
    a: SourceContribution,
    b: SourceContribution,
    length: int,
    single: Sequence[tuple[SourceContribution, int]],
) -> tuple[SourceContribution, SourceContribution]:
    """Renvoie l'occurrence gardée et l'occurrence doublon : la gardée a le rang relatif le plus proche de celui du nom dans les listes qui le citent une seule fois ; à défaut, c'est la première."""
    if not single:
        return a, b
    reference = sum((s.position or 0) / n for s, n in single) / len(single)
    if abs((b.position or 0) / length - reference) < abs((a.position or 0) / length - reference):
        return b, a
    return a, b


type WordIndex = dict[str, list[SourceContribution]]
"""Contributions sources d'une liste, par mot de leur nom, initiales exclues."""


def _words(s: SourceContribution) -> set[str]:
    return {w for w in f"{s.last_name} {s.first_name}".split() if len(w) > 1}


def _last_name_words(s: SourceContribution) -> set[str]:
    return {w for w in s.last_name.split() if len(w) > 1}


def _word_index(ordered: Sequence[SourceContribution]) -> WordIndex:
    index: WordIndex = defaultdict(list)
    for s in ordered:
        for word in _words(s):
            index[word].append(s)
    return index


def _same_author_pairs(
    ordered: Sequence[SourceContribution], index: WordIndex
) -> Iterator[tuple[SourceContribution, SourceContribution]]:
    """Renvoie les paires de contributions sources de la liste au nom d'un même auteur (`_same_author`), dans l'ordre de la liste. Seules se comparent les contributions sources dont l'une contient un mot du nom de famille de l'autre."""
    rank = {s.id: i for i, s in enumerate(ordered)}
    for a in ordered:
        later = {
            s.id: s for word in _last_name_words(a) for s in index[word] if rank[s.id] > rank[a.id]
        }
        for b in sorted(later.values(), key=lambda s: rank[s.id]):
            if _same_author(a, b):
                yield a, b


def _neighbour_pairs(
    ordered: Sequence[SourceContribution],
) -> Iterator[tuple[SourceContribution, SourceContribution]]:
    """Renvoie les paires de contributions sources voisines (`MAX_GAP_IN_LARGE_LIST`) dont un nom de famille prolonge l'autre (`_extended_last_name`), dans l'ordre de la liste."""
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 : i + 1 + MAX_GAP_IN_LARGE_LIST]:
            # Filtre rapide : un nom de famille qui prolonge l'autre le contient.
            if (a.last_name in b.last_name or b.last_name in a.last_name) and _extended_last_name(
                a.last_name, a.first_name, b.last_name, b.first_name
            ):
                yield a, b


def _same_author(a: SourceContribution, b: SourceContribution) -> bool:
    return _same_author_names(a.last_name, a.first_name, b.last_name, b.first_name)


@lru_cache(maxsize=1_000_000)
def _same_author_names(last_a: str, first_a: str, last_b: str, first_b: str) -> bool:
    """Vrai si les deux noms sont compatibles (`names_compatible`), si un nom de famille prolonge l'autre avec des initiales compatibles (`_extended_last_name`), ou si nom et prénom sont permutés (`_swapped_names`)."""
    return (
        names_compatible(last_a, first_a, last_b, first_b)
        or _extended_last_name(last_a, first_a, last_b, first_b)
        or _swapped_names(last_a, first_a, last_b, first_b)
    )


def _swapped_names(last_a: str, first_a: str, last_b: str, first_b: str) -> bool:
    """Vrai si le nom de famille de l'un est le prénom complet de l'autre, et réciproquement : « ingrid / de chazeron » et « de chazeron / ingrid »."""
    return (
        last_a != first_a
        and (last_a, first_a) == (first_b, last_b)
        and is_full_first_name(first_a)
        and is_full_first_name(first_b)
    )


@lru_cache(maxsize=1_000_000)
def _extended_last_name(last_a: str, first_a: str, last_b: str, first_b: str) -> bool:
    """Vrai si les mots d'un nom de famille sont tous dans l'autre, qui en compte davantage, et si les initiales d'un prénom commencent celles de l'autre : « porteboeuf / sarah julie » et « porteboeuf houssais / s »."""
    words_a, words_b = Counter(last_a.split()), Counter(last_b.split())
    if not words_a or not words_b or words_a == words_b:
        return False
    if not (words_a <= words_b or words_b <= words_a):
        return False
    initials_a = "".join(w[0] for w in first_a.split())
    initials_b = "".join(w[0] for w in first_b.split())
    return bool(initials_a and initials_b) and (
        initials_a.startswith(initials_b) or initials_b.startswith(initials_a)
    )


def _repeated_in_small_list(a: SourceContribution, b: SourceContribution) -> bool:
    """Vrai si l'une a un prénom complet et l'autre des initiales, ou si elles ont le même nom et le même prénom complet, dans cet ordre ou permutés (`_swapped_names`)."""
    return (
        is_full_first_name(a.first_name) != is_full_first_name(b.first_name)
        or (
            (a.last_name, a.first_name) == (b.last_name, b.first_name)
            and is_full_first_name(a.first_name)
        )
        or _swapped_names(a.last_name, a.first_name, b.last_name, b.first_name)
    )


def _namesakes(
    a: SourceContribution, b: SourceContribution, index: WordIndex
) -> list[SourceContribution]:
    """Renvoie les contributions sources d'une liste au nom de `a` ou de `b` (`_same_author`)."""
    candidates = {
        s.id: s for word in _last_name_words(a) | _last_name_words(b) for s in index.get(word, ())
    }
    return [s for s in candidates.values() if _same_author(s, a) or _same_author(s, b)]


def _orcids(a: SourceContribution, b: SourceContribution, indexes: Iterable[WordIndex]) -> set[str]:
    """Renvoie les ORCID des contributions sources de la publication au nom de `a` ou de `b`."""
    return {s.orcid for index in indexes for s in _namesakes(a, b, index) if s.orcid}


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
