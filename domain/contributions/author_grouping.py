"""Alignement des auteurs d'une publication : les contributions sources d'un même auteur forment une contribution, avec au plus une contribution source par enregistrement source.

Les liens se font d'abord par une clé de nom unique des deux côtés. Une contribution source sans lien se situe ensuite par son trou : l'intervalle entre deux liens consécutifs de la liste. Les noms se comparent dans chaque trou, puis dans tout le résidu, sans contrainte d'ordre (`domain.contributions.name_similarity`).
"""

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache

from domain.contributions.name_similarity import SIMILARITY_THRESHOLD, name_similarity
from domain.persons.name_matching import (
    first_name_initials,
    full_first_name_extends,
    is_full_first_name,
)


class GroupingMethod(StrEnum):
    """Origine de l'appartenance d'une contribution source à sa contribution. Reflet du type PostgreSQL `grouping_method`."""

    REFERENCE = "reference"
    """La contribution source fonde la contribution."""
    NAME = "name"
    """Nom de famille, nom et prénom, ou nom et initiale, uniques de part et d'autre."""
    GAP = "gap"
    """Noms semblables dans le même trou."""
    UNORDERED = "unordered"
    """Noms semblables hors de l'ordre des listes, avec un mot identique."""


_is_full_first_name = lru_cache(maxsize=1_000_000)(is_full_first_name)


@lru_cache(maxsize=1_000_000)
def with_known_first_name(first_name: str, known: str) -> str:
    """Renvoie le prénom d'une contribution source pour l'alignement : `known` quand son prénom est absent ou fait d'initiales prolongées par `known` (« z » et « zhihao »), sinon son prénom.

    Args:
        known: prénom de la personne à laquelle un humain a rattaché l'ORCID ou l'IdRef de la contribution source.
    """
    if not _is_full_first_name(known) or _is_full_first_name(first_name):
        return first_name
    if not first_name:
        return known
    initials = first_name_initials(first_name)
    if initials is not None and full_first_name_extends(initials, known):
        return known
    return first_name


def plan_contribution_ids(
    old: Mapping[int, frozenset[int]], new: Sequence[frozenset[int]]
) -> list[int | None]:
    """Renvoie l'identifiant repris par chaque contribution recalculée, ou `None`.

    Chaque contribution recalculée reprend l'identifiant de la contribution existante avec laquelle elle partage le plus de contributions sources. Chaque identifiant existant sert une seule fois, le plus petit en cas d'égalité.

    Args:
        old: contributions sources de chaque contribution existante.
        new: contributions sources de chaque contribution recalculée.
    """
    owner = {
        source_contribution_id: old_id
        for old_id, source_contribution_ids in old.items()
        for source_contribution_id in source_contribution_ids
    }
    overlaps: list[tuple[int, int, int]] = []
    for index, source_contribution_ids in enumerate(new):
        counts: dict[int, int] = {}
        for source_contribution_id in source_contribution_ids:
            if (old_id := owner.get(source_contribution_id)) is not None:
                counts[old_id] = counts.get(old_id, 0) + 1
        overlaps.extend((-count, old_id, index) for old_id, count in counts.items())
    plan: list[int | None] = [None] * len(new)
    used: set[int] = set()
    for _, old_id, index in sorted(overlaps):
        if plan[index] is None and old_id not in used:
            plan[index] = old_id
            used.add(old_id)
    return plan


@dataclass(frozen=True)
class SourceContribution:
    """Contribution source à aligner, noms normalisés."""

    id: int
    source_record: int
    position: int | None
    """Rang dans la liste ordonnée des auteurs, `None` hors de cette liste (jury de thèse chez theses.fr)."""
    last_name: str
    first_name: str


@dataclass(frozen=True)
class Member:
    """Appartenance d'une contribution source à une contribution."""

    source_contribution: int
    source_record: int
    method: GroupingMethod


@dataclass(eq=False)
class Contribution:
    """Contribution formée : sa contribution source de référence et ses contributions sources."""

    reference: SourceContribution
    members: list[Member]


def _list_order(s: SourceContribution) -> tuple[bool, int, int]:
    """Renvoie la clé de tri dans la liste : les contributions sources sans position à la fin."""
    return (s.position is None, s.position or 0, s.id)


def _name_key(s: SourceContribution) -> str:
    return s.last_name


def _full_name_key(s: SourceContribution) -> tuple[str, str] | None:
    return (
        (s.last_name, s.first_name) if s.last_name and _is_full_first_name(s.first_name) else None
    )


def _initial_key(s: SourceContribution) -> tuple[str, str] | None:
    return (s.last_name, s.first_name[:1]) if s.last_name and s.first_name else None


_NAME_KEYS: tuple[Callable[[SourceContribution], Hashable], ...] = (
    _name_key,
    _full_name_key,
    _initial_key,
)


def _similarity(
    s: SourceContribution, g: Contribution, *, exact_anchor: bool = False
) -> tuple[float, float]:
    ref = g.reference
    return name_similarity(
        s.last_name, s.first_name, ref.last_name, ref.first_name, exact_anchor=exact_anchor
    )


def _prefixes(s: SourceContribution) -> set[str]:
    """Renvoie les deux premières lettres de chaque mot complet du nom : clés de blocage des comparaisons de noms."""
    return {w[:2] for w in f"{s.last_name} {s.first_name}".split() if len(w) > 1}


class _SourceRecordLinks:
    """Liens entre un enregistrement source et les contributions déjà formées.

    Seules les contributions sources et les contributions qui ont une position entrent dans les trous. Les autres se lient par le nom, dans les étapes par clé et dans le résidu sans ordre.
    """

    def __init__(
        self,
        record_contributions: Sequence[SourceContribution],
        contributions: Sequence[Contribution],
    ) -> None:
        self.record_contributions = record_contributions
        self.contributions = contributions
        self.rank = {g: r for r, g in enumerate(contributions)}
        self.ranked = {g for g in contributions if g.reference.position is not None}
        self.links: dict[int, tuple[Contribution, GroupingMethod]] = {}
        # Contributions liées : une contribution reçoit au plus un lien.
        self.taken: set[Contribution] = set()

    def link(self, s: SourceContribution, g: Contribution, method: GroupingMethod) -> None:
        self.links[s.id] = (g, method)
        self.taken.add(g)

    def unique_pairs(self, key: Callable[[SourceContribution], Hashable]) -> None:
        """Lie une contribution source et une contribution de même clé. La clé est unique des deux côtés : parmi les contributions sources sans lien, et parmi les références des contributions sans lien."""
        by_source_contribution: dict[Hashable, list[SourceContribution]] = defaultdict(list)
        for s in self.record_contributions:
            if s.id not in self.links and (k := key(s)):
                by_source_contribution[k].append(s)
        by_reference: dict[Hashable, list[Contribution]] = defaultdict(list)
        for g in self.contributions:
            if g not in self.taken and (k := key(g.reference)):
                by_reference[k].append(g)
        for k, ss in by_source_contribution.items():
            gs = by_reference.get(k, [])
            if len(ss) == 1 and len(gs) == 1:
                self.link(ss[0], gs[0], GroupingMethod.NAME)

    def gaps(self) -> list[tuple[list[SourceContribution], list[Contribution]]]:
        """Renvoie le contenu sans lien de chaque trou présent des deux côtés : contributions sources dans l'ordre de la liste, contributions dans leur ordre. Le trou d'un élément est le nombre de liens qui le précèdent dans sa liste."""
        anchor_positions = sorted(
            s.position
            for s in self.record_contributions
            if s.id in self.links and s.position is not None
        )
        anchor_ranks = sorted(self.rank[g] for g in self.taken if g in self.ranked)
        by_gap_s: dict[int, list[SourceContribution]] = defaultdict(list)
        for s in self.record_contributions:
            if s.id not in self.links and s.position is not None:
                by_gap_s[bisect_left(anchor_positions, s.position)].append(s)
        by_gap_g: dict[int, list[Contribution]] = defaultdict(list)
        for g in self.contributions:
            if g not in self.taken and g in self.ranked:
                by_gap_g[bisect_left(anchor_ranks, self.rank[g])].append(g)
        return [(ss, by_gap_g[k]) for k, ss in by_gap_s.items() if k in by_gap_g]

    def same_size_gaps(self) -> None:
        """Dans chaque trou de même taille des deux côtés, compare les éléments un à un dans l'ordre et lie ceux aux noms semblables."""
        for ss, gs in self.gaps():
            if len(ss) == len(gs):
                for s, g in zip(ss, gs, strict=True):
                    if _similarity(s, g)[0] > SIMILARITY_THRESHOLD:
                        self.link(s, g, GroupingMethod.GAP)

    def unequal_gaps(self) -> None:
        """Dans chaque trou de tailles inégales, lie les meilleures paires de noms semblables."""
        for ss, gs in self.gaps():
            if len(ss) != len(gs):
                self.best_pairs(ss, gs, GroupingMethod.GAP)

    def unordered(self) -> None:
        """Lie les meilleures paires de noms semblables entre toutes les contributions sources et toutes les contributions restées sans lien, avec un mot identique."""
        self.best_pairs(
            [s for s in self.record_contributions if s.id not in self.links],
            [g for g in self.contributions if g not in self.taken],
            GroupingMethod.UNORDERED,
            exact_anchor=True,
        )

    def best_pairs(
        self,
        ss: Sequence[SourceContribution],
        gs: Sequence[Contribution],
        method: GroupingMethod,
        *,
        exact_anchor: bool = False,
    ) -> None:
        """Lie les paires de noms semblables, de la plus semblable à la moins semblable, chaque élément une fois. Seules se comparent les paires qui partagent les deux premières lettres d'un mot complet."""
        by_prefix: dict[str, list[int]] = defaultdict(list)
        for j, g in enumerate(gs):
            for p in _prefixes(g.reference):
                by_prefix[p].append(j)
        candidates = {(i, j) for i, s in enumerate(ss) for p in _prefixes(s) for j in by_prefix[p]}
        scored = []
        for i, j in candidates:
            score, tie_break = _similarity(ss[i], gs[j], exact_anchor=exact_anchor)
            if score > SIMILARITY_THRESHOLD:
                scored.append((-score, -tie_break, i, j))
        used_s: set[int] = set()
        used_g: set[int] = set()
        for _, _, i, j in sorted(scored):
            if i not in used_s and j not in used_g:
                self.link(ss[i], gs[j], method)
                used_s.add(i)
                used_g.add(j)

    def resolve(self) -> dict[int, tuple[Contribution, GroupingMethod]]:
        """Renvoie les liens des contributions sources de l'enregistrement source vers les contributions : clés de nom, trous de même taille, trous de tailles inégales, puis résidu sans ordre."""
        for key in _NAME_KEYS:
            self.unique_pairs(key)
        self.same_size_gaps()
        self.unequal_gaps()
        self.unordered()
        return self.links


def _swapped(s: SourceContribution) -> SourceContribution:
    return replace(s, last_name=s.first_name, first_name=s.last_name)


def _inverted(
    record_contributions: Sequence[SourceContribution], contributions: Sequence[Contribution]
) -> bool:
    """Vrai si l'enregistrement source donne le prénom à la place du nom de famille : plus de ses prénoms que de ses noms de famille sont des noms de famille de contributions."""
    last_names = {g.reference.last_name for g in contributions if g.reference.last_name}
    direct = sum(s.last_name in last_names for s in record_contributions)
    swapped = sum(bool(s.first_name) and s.first_name in last_names for s in record_contributions)
    return swapped > direct


def align_publication(
    source_records: Mapping[int, Sequence[SourceContribution]],
    *,
    deferred: Collection[int] = (),
) -> list[Contribution]:
    """Aligne les auteurs d'une publication, et renvoie ses contributions.

    Les enregistrements sources se traitent du plus long au plus court, chacun face aux contributions déjà formées. À longueur égale, les enregistrements sources `deferred` passent après les autres, puis l'ordre suit leur identifiant. Un enregistrement source qui intervertit nom de famille et prénom (`_inverted`) s'aligne avec ses noms remis dans l'ordre.
    """
    contributions: list[Contribution] = []
    order = sorted(source_records, key=lambda n: (-len(source_records[n]), n in deferred, n))
    for i, source_record_id in enumerate(order):
        record_contributions = sorted(source_records[source_record_id], key=_list_order)
        if i and _inverted(record_contributions, contributions):
            record_contributions = [_swapped(s) for s in record_contributions]
        links = _SourceRecordLinks(record_contributions, contributions).resolve() if i else {}
        contributions = _with_new_contributions(
            contributions, record_contributions, links, source_record_id
        )
    return contributions


def _with_new_contributions(
    contributions: Sequence[Contribution],
    record_contributions: Sequence[SourceContribution],
    links: Mapping[int, tuple[Contribution, GroupingMethod]],
    source_record_id: int,
) -> list[Contribution]:
    """Range les contributions après l'alignement d'un enregistrement source : ses contributions sources liées rejoignent leur contribution, les autres fondent une contribution.

    Une contribution fondée se range juste après la contribution de la dernière contribution source liée qui précède sa fondatrice dans la liste, ou en tête. Les contributions fondées sans position se rangent à la fin.
    """
    following: dict[Contribution | None, list[Contribution]] = defaultdict(list)
    unpositioned: list[Contribution] = []
    previous: Contribution | None = None
    for s in record_contributions:
        if (link := links.get(s.id)) is not None:
            contribution, method = link
            contribution.members.append(Member(s.id, source_record_id, method))
            previous = contribution
        else:
            contribution = Contribution(
                s, [Member(s.id, source_record_id, GroupingMethod.REFERENCE)]
            )
            (unpositioned if s.position is None else following[previous]).append(contribution)
    return [
        *following[None],
        *(placed for g in contributions for placed in (g, *following[g])),
        *unpositioned,
    ]
