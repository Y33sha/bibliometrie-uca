"""Groupes de contributions sources : les contributions sources d'un même auteur dans une publication, avec au maximum une contribution source par enregistrement source.

Les enregistrements sources d'une publication se traitent de la plus longue liste d'auteurs à la plus courte, chacune face aux groupes déjà formés. Ce module réunit les décisions pures : ordre des liens, trous, poids du modèle du résidu, réconciliation des identifiants de groupes.
"""

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache
from typing import NamedTuple

from domain.persons.name_matching import first_name_initials, full_first_name_extends, is_initials
from domain.source_records.metadata_correction.shared_doi import DoiClusterCase

REPEATED_LIST_CASES: frozenset[str] = frozenset(
    {DoiClusterCase.DATACITE_VERSION_TO_CONCEPT, DoiClusterCase.DATACITE_PACKAGE_PIECE}
)
"""Cas de convergence écartés de l'alignement : versions d'un concept, pièces d'un jeu de données. Leur liste d'auteurs se répète d'un enregistrement source à l'autre. Un enregistrement source de l'un de ces cas est écarté quand la publication a un enregistrement source hors de ces cas."""


class GroupingMethod(StrEnum):
    """Origine de l'appartenance d'une contribution source à son groupe. Mappe l'enum PostgreSQL `grouping_method`."""

    REFERENCE = "reference"
    """La contribution source fonde le groupe."""
    NAME = "name"
    """Patronyme, prénom ou initiale, uniques de part et d'autre."""
    IDENTIFIER = "identifier"
    """ORCID ou IdRef partagé, à patronyme égal."""
    ORDER = "order"
    """Rang parmi les contributions sources de même patronyme et de même initiale."""
    MODEL = "model"
    """Modèle probabiliste, avec un score et une marge."""


def full_first_name(first_name: str) -> str:
    """Prénom complet, ou chaîne vide quand le prénom se réduit à des initiales."""
    return "" if not first_name or _is_initials(first_name) else first_name


@lru_cache(maxsize=1_000_000)
def with_known_first_name(first_name: str, known: str) -> str:
    """Prénom d'une contribution source pour l'alignement : `known` quand son prénom est absent ou fait d'initiales que `known` prolonge (« z » et « zhihao »), sinon son prénom.

    `known` : prénom de la personne à laquelle un humain a rattaché l'ORCID ou l'IdRef de la contribution source.
    """
    if not full_first_name(known) or full_first_name(first_name):
        return first_name
    if not first_name:
        return known
    initials = first_name_initials(first_name)
    if initials is not None and full_first_name_extends(initials, known):
        return known
    return first_name


def longest_ordered(links: Iterable[tuple[int, int, int]]) -> set[int]:
    """Identifiants de la plus longue suite de liens (position dans l'enregistrement source, rang du groupe, identifiant) dont les rangs croissent avec les positions."""
    items = sorted(links)
    tails: list[int] = []
    tail_index: list[int] = []
    previous = [-1] * len(items)
    for i, (_, rank, _) in enumerate(items):
        k = bisect_left(tails, rank)
        if k == len(tails):
            tails.append(rank)
            tail_index.append(i)
        else:
            tails[k] = rank
            tail_index[k] = i
        previous[i] = tail_index[k - 1] if k else -1
    kept: set[int] = set()
    i = tail_index[-1] if tail_index else -1
    while i >= 0:
        kept.add(items[i][2])
        i = previous[i]
    return kept


def gap(anchors: Sequence[int], value: int) -> int:
    """Indice du trou où tombe `value` : nombre de valeurs de `anchors` (triées) qui le précèdent."""
    return bisect_left(anchors, value)


@lru_cache(maxsize=1_000_000)
def jaro_winkler(a: str, b: str) -> float:
    """Similarité de Jaro-Winkler, comme `jaro_winkler_similarity` de DuckDB : demi-transpositions arrondies à l'entier inférieur ; bonus de préfixe au-delà de 0,7, sur 4 caractères au plus, facteur 0,1."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(max(la, lb) // 2 - 1, 0)
    matched_a, matched_b = [False] * la, [False] * lb
    matches = 0
    for i, char in enumerate(a):
        for j in range(max(0, i - window), min(lb, i + window + 1)):
            if not matched_b[j] and b[j] == char:
                matched_a[i] = matched_b[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions, j = 0, 0
    for i in range(la):
        if matched_a[i]:
            while not matched_b[j]:
                j += 1
            transpositions += a[i] != b[j]
            j += 1
    jaro = (matches / la + matches / lb + (matches - transpositions // 2) / matches) / 3
    if jaro <= 0.7:
        return jaro
    prefix = 0
    for char_a, char_b in zip(a[:4], b[:4], strict=False):
        if char_a != char_b:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


@dataclass(frozen=True)
class Author:
    """Ce qu'une contribution source ou un membre de groupe expose au modèle du résidu : noms normalisés, identifiants, trou."""

    last_name: str
    first_name: str
    orcid: str
    idref: str
    gap: int


@lru_cache(maxsize=1_000_000)
def _initials(first_name: str) -> str:
    return "".join(part[:1] for part in first_name.split())


_is_initials = lru_cache(maxsize=1_000_000)(is_initials)


class Comparison(StrEnum):
    """Comparaison du modèle du résidu ; la valeur est le nom de colonne du modèle Splink."""

    LAST_NAME = "ln"
    FIRST_NAME = "fn"
    ORCID = "orcid"
    IDREF = "idref"
    GAP = "gap"


class ComparisonLevel(StrEnum):
    """Niveau d'une comparaison du modèle du résidu ; la valeur est le libellé du niveau dans le modèle Splink."""

    LAST_NAME_EXACT = "Exact match on ln"
    REVERSED = "reversed"
    WORDS_INCLUDED = "mots inclus"
    JW_092 = "jw 0.92"
    JW_08 = "jw 0.8"
    FIRST_NAME_EXACT = "Exact match on fn"
    INITIALS_MATCH = "initiales concordantes"
    JW_09 = "jw 0.9"
    IDENTIFIER_EXACT = "exact"
    SAME_GAP = "même trou"
    NEXT_GAP = "trou voisin"
    ELSEWHERE = "ailleurs"
    # Aucun des niveaux de ressemblance de la comparaison.
    ELSE = "else"


JARO_WINKLER_THRESHOLDS: dict[ComparisonLevel, float] = {
    ComparisonLevel.JW_092: 0.92,
    ComparisonLevel.JW_08: 0.8,
    ComparisonLevel.JW_09: 0.9,
}
"""Similarité de Jaro-Winkler minimale de chaque niveau ; l'estimation des poids du modèle les reprend."""

# Seuils lus une fois : `comparison_levels` s'exécute pour chaque paire du résidu.
_JW_092 = JARO_WINKLER_THRESHOLDS[ComparisonLevel.JW_092]
_JW_08 = JARO_WINKLER_THRESHOLDS[ComparisonLevel.JW_08]
_JW_09 = JARO_WINKLER_THRESHOLDS[ComparisonLevel.JW_09]


def comparison_levels(x: Author, y: Author) -> dict[Comparison, ComparisonLevel | None]:
    """Niveau de chaque comparaison du modèle du résidu entre deux auteurs ; `None` quand une valeur manque."""
    levels: dict[Comparison, ComparisonLevel | None] = {}
    lx, ly = x.last_name, y.last_name
    if not lx or not ly:
        levels[Comparison.LAST_NAME] = None
    elif lx == ly:
        levels[Comparison.LAST_NAME] = ComparisonLevel.LAST_NAME_EXACT
    elif lx == y.first_name and ly == x.first_name:
        levels[Comparison.LAST_NAME] = ComparisonLevel.REVERSED
    elif set(lx.split()) <= set(ly.split()) or set(ly.split()) <= set(lx.split()):
        levels[Comparison.LAST_NAME] = ComparisonLevel.WORDS_INCLUDED
    elif jaro_winkler(lx, ly) >= _JW_092:
        levels[Comparison.LAST_NAME] = ComparisonLevel.JW_092
    elif jaro_winkler(lx, ly) >= _JW_08:
        levels[Comparison.LAST_NAME] = ComparisonLevel.JW_08
    else:
        levels[Comparison.LAST_NAME] = ComparisonLevel.ELSE
    fx, fy = x.first_name, y.first_name
    if not fx or not fy:
        levels[Comparison.FIRST_NAME] = None
    elif fx == fy:
        levels[Comparison.FIRST_NAME] = ComparisonLevel.FIRST_NAME_EXACT
    elif (_is_initials(fx) or _is_initials(fy)) and (
        _initials(fx).startswith(_initials(fy)) or _initials(fy).startswith(_initials(fx))
    ):
        levels[Comparison.FIRST_NAME] = ComparisonLevel.INITIALS_MATCH
    elif jaro_winkler(fx, fy) >= _JW_09:
        levels[Comparison.FIRST_NAME] = ComparisonLevel.JW_09
    else:
        levels[Comparison.FIRST_NAME] = ComparisonLevel.ELSE
    for comparison, vx, vy in (
        (Comparison.ORCID, x.orcid, y.orcid),
        (Comparison.IDREF, x.idref, y.idref),
    ):
        levels[comparison] = (
            None
            if not vx or not vy
            else (ComparisonLevel.IDENTIFIER_EXACT if vx == vy else ComparisonLevel.ELSE)
        )
    distance = abs(x.gap - y.gap)
    levels[Comparison.GAP] = (
        ComparisonLevel.SAME_GAP
        if distance == 0
        else (ComparisonLevel.NEXT_GAP if distance == 1 else ComparisonLevel.ELSEWHERE)
    )
    return levels


def position_only(x: Author, y: Author) -> bool:
    """Seule la position rapproche les deux auteurs : patronymes sans ressemblance, prénoms sans ressemblance ou absents, aucun identifiant commun."""
    return _position_only(comparison_levels(x, y))


def _position_only(levels: Mapping[Comparison, ComparisonLevel | None]) -> bool:
    return (
        levels[Comparison.LAST_NAME] == ComparisonLevel.ELSE
        and levels[Comparison.FIRST_NAME] in (ComparisonLevel.ELSE, None)
        and ComparisonLevel.IDENTIFIER_EXACT
        not in (levels[Comparison.ORCID], levels[Comparison.IDREF])
    )


@dataclass(frozen=True)
class ResidualModel:
    """Poids en bits de chaque niveau de comparaison du modèle du résidu."""

    weights: Mapping[str, Mapping[str, float]]

    def score(self, x: Author, y: Author) -> float:
        """Somme des poids des comparaisons entre deux auteurs, sans a priori."""
        return self.score_levels(comparison_levels(x, y))

    def score_levels(self, levels: Mapping[Comparison, ComparisonLevel | None]) -> float:
        """Somme des poids de niveaux de comparaison déjà calculés."""
        return sum(
            self.weights[name].get(level, 0.0)
            for name, level in levels.items()
            if level is not None
        )


def link_threshold(candidate_groups: int) -> float:
    """Score au-delà duquel un lien du résidu est retenu : log2 du nombre de groupes candidats, soit une probabilité supérieure à 1/2 avec un a priori de 1 sur ce nombre."""
    return math.log2(max(candidate_groups, 2))


def plan_group_ids(
    old: Mapping[int, frozenset[int]], new: Sequence[frozenset[int]]
) -> list[int | None]:
    """Identifiant repris par chaque nouveau groupe, ou `None`.

    Chaque nouveau groupe reprend l'identifiant de l'ancien groupe avec lequel il partage le plus de contributions sources, chaque ancien identifiant une seule fois, le plus petit en cas d'égalité. `old` : contributions sources de chaque ancien groupe ; `new` : contributions sources de chaque nouveau groupe.
    """
    owner = {
        contribution: old_id
        for old_id, contributions in old.items()
        for contribution in contributions
    }
    overlaps: list[tuple[int, int, int]] = []
    for index, contributions in enumerate(new):
        counts: dict[int, int] = {}
        for contribution in contributions:
            if (old_id := owner.get(contribution)) is not None:
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
    """Contribution source à grouper : enregistrement source, position dans la liste, noms normalisés, identifiants. Une contribution source hors de la liste ordonnée (jury de thèse chez theses.fr) est sans position."""

    id: int
    source_record: int
    position: int | None
    last_name: str
    first_name: str
    orcid: str = ""
    idref: str = ""


@dataclass(frozen=True)
class Member:
    """Appartenance d'une contribution source à un groupe ; `score` et `margin` en bits pour `GroupingMethod.MODEL`."""

    source_contribution: int
    source_record: int
    method: GroupingMethod
    score: float | None = None
    margin: float | None = None


@dataclass
class Group:
    """Groupe formé : sa contribution source de référence et ses membres."""

    index: int
    reference: SourceContribution
    members: list[Member]


type Assign = Callable[[Sequence[Sequence[float]]], Iterable[tuple[int, int]]]
"""Affectation de gain maximal sur une matrice de gains : paires (ligne, colonne)."""

type ResidualSink = Callable[[int, Sequence[Author], Sequence[Author]], None]
"""Reçoit le résidu de la règle pour un enregistrement source : son identifiant, ses contributions sources sans lien, puis les contributions sources de référence des groupes sans lien, chacune avec son trou."""


def _list_order(s: SourceContribution) -> tuple[bool, int, int]:
    """Clé de tri dans la liste : les contributions sources sans position à la fin."""
    return (s.position is None, s.position or 0, s.id)


def _name_key(s: SourceContribution) -> str:
    return s.last_name


def _full_name_key(s: SourceContribution) -> tuple[str, str] | None:
    full = full_first_name(s.first_name)
    return (s.last_name, full) if s.last_name and full else None


def _initial_key(s: SourceContribution) -> tuple[str, str] | None:
    return (s.last_name, s.first_name[:1]) if s.last_name and s.first_name else None


class _SourceRecordLinks:
    """Liens de la règle entre un enregistrement source et les groupes déjà formés.

    Seuls les contributions sources et les groupes qui ont une position entrent dans le filtre d'ordre, les trous et le résidu. Les autres se lient par le nom et l'identifiant.
    """

    def __init__(
        self,
        contributions: Sequence[SourceContribution],
        groups: Sequence[Group],
        source_contributions: Mapping[int, SourceContribution] | None = None,
    ) -> None:
        self.contributions = contributions
        self.groups = groups
        # Contributions sources des membres des groupes, pour comparer les identifiants à tout le groupe.
        self.source_contributions = source_contributions or {}
        self.rank = {g.index: r for r, g in enumerate(groups)}
        self.ranked = {g.index for g in groups if g.reference.position is not None}
        self.links: dict[int, int] = {}
        self.methods: dict[int, GroupingMethod] = {}
        self.forbidden: set[tuple[int, int]] = set()

    def link(self, s: SourceContribution, g: Group, method: GroupingMethod) -> None:
        if (s.id, g.index) not in self.forbidden:
            self.links[s.id] = g.index
            self.methods[s.id] = method

    def linked_groups(self) -> set[int]:
        return set(self.links.values())

    def unique_pairs(
        self, key: Callable[[SourceContribution], object], method: GroupingMethod
    ) -> None:
        """Lie une contribution source et un groupe quand leur clé est unique des deux côtés, parmi les contributions sources et groupes sans lien."""
        taken = self.linked_groups()
        by_contribution: dict[object, list[SourceContribution]] = {}
        by_group: dict[object, list[Group]] = {}
        for s in self.contributions:
            if s.id not in self.links and (k := key(s)):
                by_contribution.setdefault(k, []).append(s)
        for g in self.groups:
            if g.index not in taken and (k := key(g.reference)):
                by_group.setdefault(k, []).append(g)
        for k, ss in by_contribution.items():
            gs = by_group.get(k, [])
            if len(ss) == 1 and len(gs) == 1:
                self.link(ss[0], gs[0], method)

    def _members(self, g: Group) -> list[SourceContribution]:
        return [
            self.source_contributions.get(m.source_contribution, g.reference) for m in g.members
        ]

    def shared_identifier(self) -> None:
        """Lie une contribution source au groupe dont un membre partage son ORCID ou son IdRef, à patronyme égal. Un identifiant présent dans plusieurs groupes ne lie rien."""
        by_identifier: dict[tuple[str, str, str], set[int]] = defaultdict(set)
        for g in self.groups:
            for m in self._members(g):
                if m.last_name and m.orcid:
                    by_identifier[("orcid", m.last_name, m.orcid)].add(g.index)
                if m.last_name and m.idref:
                    by_identifier[("idref", m.last_name, m.idref)].add(g.index)
        by_index = {g.index: g for g in self.groups}
        for s in self.contributions:
            if s.id in self.links or not s.last_name:
                continue
            candidates = (
                by_identifier.get(("orcid", s.last_name, s.orcid), set()) if s.orcid else set()
            )
            if not candidates and s.idref:
                candidates = by_identifier.get(("idref", s.last_name, s.idref), set())
            if (
                len(candidates) == 1
                and (index := next(iter(candidates))) not in self.linked_groups()
            ):
                self.link(s, by_index[index], GroupingMethod.IDENTIFIER)

    def name_steps(self) -> None:
        self.unique_pairs(_name_key, GroupingMethod.NAME)
        self.unique_pairs(_full_name_key, GroupingMethod.NAME)
        self.unique_pairs(_initial_key, GroupingMethod.NAME)
        self.shared_identifier()

    def _in_order(self, s: SourceContribution) -> bool:
        """Le lien de `s` entre dans le filtre d'ordre : le groupe a une position, et le lien ne vient pas d'un identifiant."""
        return self.links[s.id] in self.ranked and self.methods[s.id] != GroupingMethod.IDENTIFIER

    def order_filter(self) -> None:
        """Garde la plus longue suite de liens rangés dans le même ordre des deux côtés ; écarte et interdit les autres. Un lien par identifiant, ou d'une contribution source ou d'un groupe sans position, reste."""
        ordered = [
            (s.position, self.rank[self.links[s.id]], s.id)
            for s in self.contributions
            if s.id in self.links and s.position is not None and self._in_order(s)
        ]
        kept = longest_ordered(ordered)
        for _, _, source_contribution_id in ordered:
            if source_contribution_id not in kept:
                self.forbidden.add((source_contribution_id, self.links.pop(source_contribution_id)))
                del self.methods[source_contribution_id]

    def gaps(self) -> tuple[dict[int, int], dict[int, int]]:
        """Trou de chaque contribution source et de chaque groupe restés sans lien, parmi ceux qui ont une position."""
        taken = self.linked_groups()
        anchor_positions = sorted(
            s.position for s in self.contributions if s.id in self.links and s.position is not None
        )
        anchor_ranks = sorted(self.rank[g] for g in taken if g in self.ranked)
        contribution_gaps = {
            s.id: gap(anchor_positions, s.position)
            for s in self.contributions
            if s.id not in self.links and s.position is not None
        }
        group_gaps = {
            g.index: gap(anchor_ranks, self.rank[g.index])
            for g in self.groups
            if g.index not in taken and g.index in self.ranked
        }
        return contribution_gaps, group_gaps

    def order_in_gaps(self) -> None:
        """Dans chaque trou, patronyme et initiale en nombre égal des deux côtés : lien dans l'ordre des positions."""
        contribution_gaps, group_gaps = self.gaps()
        by_contribution: dict[tuple[str, str, int], list[SourceContribution]] = {}
        by_group: dict[tuple[str, str, int], list[Group]] = {}
        for s in self.contributions:
            if s.id in contribution_gaps and s.last_name:
                by_contribution.setdefault(
                    (s.last_name, s.first_name[:1], contribution_gaps[s.id]), []
                ).append(s)
        for g in self.groups:
            if g.index in group_gaps and g.reference.last_name:
                ref = g.reference
                key = (ref.last_name, ref.first_name[:1], group_gaps[g.index])
                by_group.setdefault(key, []).append(g)
        for k, ss in by_contribution.items():
            gs = by_group.get(k, [])
            if len(ss) > 1 and len(ss) == len(gs):
                for s, g in zip(ss, gs, strict=True):
                    self.link(s, g, GroupingMethod.ORDER)

    def resolve(
        self,
        source_record_id: int,
        *,
        model: ResidualModel | None = None,
        assign: Assign | None = None,
        on_residual: ResidualSink | None = None,
    ) -> dict[int, "_Link"]:
        """Liens des contributions sources de l'enregistrement source vers les groupes : noms et identifiants, filtre d'ordre deux fois, ordre dans les trous, puis le résidu par le modèle quand `model` et `assign` sont donnés. `on_residual` reçoit le résidu de la règle, avant le modèle."""
        self.name_steps()
        self.order_filter()
        self.name_steps()
        self.order_filter()
        self.order_in_gaps()
        if on_residual is not None:
            contribution_gaps, group_gaps = self.gaps()
            on_residual(
                source_record_id,
                [
                    _author(s, contribution_gaps[s.id])
                    for s in self.contributions
                    if s.id in contribution_gaps
                ],
                [
                    _author(g.reference, group_gaps[g.index])
                    for g in self.groups
                    if g.index in group_gaps
                ],
            )
        links = {s: _Link(g, self.methods[s]) for s, g in self.links.items()}
        if model is not None and assign is not None:
            residual = _residual_links(self, self.source_contributions, model, assign)
            for contribution, (g, score, margin) in residual.items():
                links[contribution] = _Link(g, GroupingMethod.MODEL, score, margin)
        return links


class _Link(NamedTuple):
    """Lien d'une contribution source vers le groupe d'indice `group`, avec le score et la marge d'un lien du modèle."""

    group: int
    method: GroupingMethod
    score: float | None = None
    margin: float | None = None


def _author(s: SourceContribution, gap_index: int) -> Author:
    return Author(s.last_name, s.first_name, s.orcid, s.idref, gap_index)


def _swapped(s: SourceContribution) -> SourceContribution:
    return replace(s, last_name=s.first_name, first_name=s.last_name)


def _inverted(contributions: Sequence[SourceContribution], groups: Sequence[Group]) -> bool:
    """L'enregistrement source donne le prénom à la place du patronyme : plus de ses prénoms que de ses patronymes sont des patronymes de groupes."""
    last_names = {g.reference.last_name for g in groups if g.reference.last_name}
    direct = sum(s.last_name in last_names for s in contributions)
    swapped = sum(bool(s.first_name) and s.first_name in last_names for s in contributions)
    return swapped > direct


def _residual_links(
    record_links: _SourceRecordLinks,
    source_contributions: Mapping[int, SourceContribution],
    model: ResidualModel,
    assign: Assign,
) -> dict[int, tuple[int, float, float]]:
    """Liens du résidu : contribution source → (indice de groupe, score, marge).

    Une paire candidate partage un trou ou un trou voisin, les deux premières lettres du patronyme, ou un identifiant. Son score est le meilleur face aux membres du groupe que la position seule ne rapproche pas (`position_only`). Un lien est retenu quand le score dépasse `link_threshold` du nombre de groupes restants.
    """
    contribution_gaps, group_gaps = record_links.gaps()
    rest_contributions = [s for s in record_links.contributions if s.id in contribution_gaps]
    rest_groups = [g for g in record_links.groups if g.index in group_gaps]
    if not rest_contributions or not rest_groups:
        return {}
    threshold = link_threshold(len(rest_groups))
    members = {
        g.index: [
            _author(source_contributions[m.source_contribution], group_gaps[g.index])
            for m in g.members
        ]
        for g in rest_groups
    }
    # Index de blocage : groupes par trou, par deux premières lettres d'un patronyme de membre, par identifiant de membre.
    by_gap: dict[int, set[int]] = defaultdict(set)
    by_prefix: dict[str, set[int]] = defaultdict(set)
    by_orcid: dict[str, set[int]] = defaultdict(set)
    by_idref: dict[str, set[int]] = defaultdict(set)
    for index, authors in members.items():
        by_gap[group_gaps[index]].add(index)
        for y in authors:
            by_prefix[y.last_name[:2]].add(index)
            if y.orcid:
                by_orcid[y.orcid].add(index)
            if y.idref:
                by_idref[y.idref].add(index)
    gains: dict[tuple[int, int], float] = {}
    for s in rest_contributions:
        x = _author(s, contribution_gaps[s.id])
        candidates = (
            by_gap.get(x.gap - 1, set())
            | by_gap.get(x.gap, set())
            | by_gap.get(x.gap + 1, set())
            | by_prefix.get(x.last_name[:2], set())
            | (by_orcid.get(x.orcid, set()) if x.orcid else set())
            | (by_idref.get(x.idref, set()) if x.idref else set())
        )
        for index in candidates:
            kept = [
                (y, levels)
                for y in members[index]
                if not _position_only(levels := comparison_levels(x, y))
            ]
            # Le blocage ne retient que les membres que la position seule ne rapproche pas ; le trou est celui du groupe.
            if not kept or not (
                abs(x.gap - group_gaps[index]) <= 1
                or any(
                    x.last_name[:2] == y.last_name[:2]
                    or (x.orcid and x.orcid == y.orcid)
                    or (x.idref and x.idref == y.idref)
                    for y, _ in kept
                )
            ):
                continue
            gain = max(model.score_levels(levels) for _, levels in kept) - threshold
            if gain > 0:
                gains[(s.id, index)] = gain
    if not gains:
        return {}
    rows = sorted({s for s, _ in gains})
    cols = sorted({g for _, g in gains})
    matrix = [[gains.get((s, g), 0.0) for g in cols] for s in rows]
    out: dict[int, tuple[int, float, float]] = {}
    for i, j in assign(matrix):
        gain = matrix[i][j]
        if gain <= 0:
            continue
        others = [matrix[i][c] for c in range(len(cols)) if c != j]
        others += [matrix[r][j] for r in range(len(rows)) if r != i]
        out[rows[i]] = (cols[j], gain + threshold, gain - max(others, default=0.0))
    return out


def align_publication(
    source_records: Mapping[int, Sequence[SourceContribution]],
    *,
    model: ResidualModel | None = None,
    assign: Assign | None = None,
    on_residual: ResidualSink | None = None,
    deferred: Collection[int] = (),
) -> list[Group]:
    """Groupes de contributions sources d'une publication.

    Les enregistrements sources se traitent du plus long au plus court, chacun face aux groupes déjà formés. À longueur égale, les enregistrements sources `deferred` passent après les autres, puis l'ordre suit leur identifiant. Un enregistrement source qui intervertit patronyme et prénom (`_inverted`) s'aligne avec ses noms remis dans l'ordre. `model` et `assign` lient en plus le résidu. `on_residual` reçoit le résidu de la règle, avant le modèle.
    """
    source_contributions = {
        s.id: s for contributions in source_records.values() for s in contributions
    }
    groups: list[Group] = []
    order = sorted(source_records, key=lambda n: (-len(source_records[n]), n in deferred, n))
    for i, source_record_id in enumerate(order):
        contributions = sorted(source_records[source_record_id], key=_list_order)
        if i and _inverted(contributions, groups):
            contributions = [_swapped(s) for s in contributions]
            source_contributions.update((s.id, s) for s in contributions)
        links = (
            _SourceRecordLinks(contributions, groups, source_contributions).resolve(
                source_record_id, model=model, assign=assign, on_residual=on_residual
            )
            if i
            else {}
        )
        by_index = {g.index: g for g in groups}
        for s in contributions:
            if (link := links.get(s.id)) is not None:
                member = Member(s.id, source_record_id, link.method, link.score, link.margin)
                by_index[link.group].members.append(member)
            else:
                member = Member(s.id, source_record_id, GroupingMethod.REFERENCE)
                groups.append(Group(len(groups), s, [member]))
        groups.sort(key=lambda g: (*_list_order(g.reference)[:2], g.index))
    return groups
