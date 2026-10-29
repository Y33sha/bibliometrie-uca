"""Contributions : les contributions sources d'un même auteur dans une publication, avec au maximum une contribution source par enregistrement source.

Les enregistrements sources d'une publication se traitent de la plus longue liste d'auteurs à la plus courte, chacune face aux contributions déjà formées. Ce module réunit les décisions pures : ordre des liens, trous, poids du modèle du résidu, réconciliation des identifiants de contributions.
"""

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import cached_property, lru_cache
from typing import NamedTuple

from domain.persons.name_matching import first_name_initials, full_first_name_extends, is_initials


class GroupingMethod(StrEnum):
    """Origine de l'appartenance d'une contribution source à sa contribution. Mappe l'enum PostgreSQL `grouping_method`."""

    REFERENCE = "reference"
    """La contribution source fonde la contribution."""
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
    """Identifiants de la plus longue suite de liens (position dans l'enregistrement source, rang de la contribution, identifiant) dont les rangs croissent avec les positions."""
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
    """Ce qu'une contribution source expose au modèle du résidu : noms normalisés, identifiants, trou."""

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
        and not _shared_identifier(levels)
    )


def conflicting_initials(x: Author, y: Author) -> bool:
    """Patronymes seulement proches et premières initiales différentes, sans identifiant commun : « V. Balakrishnan » et « S. Balaji »."""
    return _conflicting_initials(x, y, comparison_levels(x, y))


def _conflicting_initials(
    x: Author, y: Author, levels: Mapping[Comparison, ComparisonLevel | None]
) -> bool:
    return (
        levels[Comparison.LAST_NAME]
        in (ComparisonLevel.JW_092, ComparisonLevel.JW_08, ComparisonLevel.ELSE)
        and bool(x.first_name)
        and bool(y.first_name)
        and x.first_name[0] != y.first_name[0]
        and not _shared_identifier(levels)
    )


def _shared_identifier(levels: Mapping[Comparison, ComparisonLevel | None]) -> bool:
    return ComparisonLevel.IDENTIFIER_EXACT in (levels[Comparison.ORCID], levels[Comparison.IDREF])


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


def link_threshold(candidate_contributions: int) -> float:
    """Score au-delà duquel un lien du résidu est retenu : log2 du nombre de contributions candidates, soit une probabilité supérieure à 1/2 avec un a priori de 1 sur ce nombre."""
    return math.log2(max(candidate_contributions, 2))


def plan_contribution_ids(
    old: Mapping[int, frozenset[int]], new: Sequence[frozenset[int]]
) -> list[int | None]:
    """Identifiant repris par chaque nouvelle contribution, ou `None`.

    Chaque nouvelle contribution reprend l'identifiant de l'ancienne contribution avec laquelle elle partage le plus de contributions sources, chaque ancien identifiant une seule fois, le plus petit en cas d'égalité. `old` : contributions sources de chaque ancienne contribution ; `new` : contributions sources de chaque nouvelle contribution.
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
    """Contribution source à aligner : enregistrement source, position dans la liste, noms normalisés, identifiants. Une contribution source hors de la liste ordonnée (jury de thèse chez theses.fr) est sans position."""

    id: int
    source_record: int
    position: int | None
    last_name: str
    first_name: str
    orcid: str = ""
    idref: str = ""


@dataclass(frozen=True)
class Member:
    """Appartenance d'une contribution source à une contribution ; `score` et `margin` en bits pour `GroupingMethod.MODEL`."""

    source_contribution: int
    source_record: int
    method: GroupingMethod
    score: float | None = None
    margin: float | None = None


@dataclass
class Contribution:
    """Contribution formée : sa contribution source de référence et ses contributions sources."""

    index: int
    reference: SourceContribution
    members: list[Member]


type Assign = Callable[[Sequence[Sequence[float]]], Iterable[tuple[int, int]]]
"""Affectation de gain maximal sur une matrice de gains : paires (ligne, colonne)."""

type ResidualSink = Callable[[int, Sequence[Author], Sequence[Author]], None]
"""Reçoit le résidu de la règle pour un enregistrement source : son identifiant, ses contributions sources sans lien, puis les contributions sources de référence des contributions sans lien, chacune avec son trou."""


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
    """Liens de la règle entre un enregistrement source et les contributions déjà formées.

    Seules les contributions sources et les contributions qui ont une position entrent dans le filtre d'ordre, les trous et le résidu. Les autres se lient par le nom et l'identifiant.
    """

    def __init__(
        self,
        record_contributions: Sequence[SourceContribution],
        contributions: Sequence[Contribution],
        source_contributions: Mapping[int, SourceContribution] | None = None,
    ) -> None:
        self.record_contributions = record_contributions
        self.contributions = contributions
        # Contributions sources des contributions sources des contributions, pour comparer les identifiants à tout la contribution.
        self.source_contributions = source_contributions or {}
        self.rank = {g.index: r for r, g in enumerate(contributions)}
        self.ranked = {g.index for g in contributions if g.reference.position is not None}
        self.links: dict[int, int] = {}
        self.methods: dict[int, GroupingMethod] = {}
        # Contributions liées : une contribution reçoit au plus un lien.
        self.taken: set[int] = set()
        self.forbidden: set[tuple[int, int]] = set()
        self.by_index = {g.index: g for g in contributions}
        self._contribution_indexes: dict[
            Callable[[SourceContribution], object], dict[object, list[Contribution]]
        ] = {}

    def link(self, s: SourceContribution, g: Contribution, method: GroupingMethod) -> None:
        if (s.id, g.index) not in self.forbidden:
            self.links[s.id] = g.index
            self.methods[s.id] = method
            self.taken.add(g.index)

    def unlink(self, source_contribution_id: int) -> None:
        """Retire le lien de la contribution source et l'interdit."""
        contribution = self.links.pop(source_contribution_id)
        del self.methods[source_contribution_id]
        self.taken.discard(contribution)
        self.forbidden.add((source_contribution_id, contribution))

    def _contributions_by(
        self, key: Callable[[SourceContribution], object]
    ) -> dict[object, list[Contribution]]:
        """Contributions par clé de leur contribution source de référence."""
        index = self._contribution_indexes.get(key)
        if index is None:
            index = {}
            for g in self.contributions:
                if k := key(g.reference):
                    index.setdefault(k, []).append(g)
            self._contribution_indexes[key] = index
        return index

    def unique_pairs(
        self,
        key: Callable[[SourceContribution], object],
        record_contributions: Sequence[SourceContribution],
    ) -> None:
        """Lie une contribution source et une contribution quand leur clé est unique des deux côtés, parmi les contributions sources données et les contributions restées sans lien."""
        by_source_contribution: dict[object, list[SourceContribution]] = {}
        for s in record_contributions:
            if s.id not in self.links and (k := key(s)):
                by_source_contribution.setdefault(k, []).append(s)
        by_contribution = self._contributions_by(key)
        for k, ss in by_source_contribution.items():
            if len(ss) != 1:
                continue
            gs = [g for g in by_contribution.get(k, []) if g.index not in self.taken]
            if len(gs) == 1:
                self.link(ss[0], gs[0], GroupingMethod.NAME)

    def _members(self, g: Contribution) -> list[SourceContribution]:
        return [
            self.source_contributions.get(m.source_contribution, g.reference) for m in g.members
        ]

    @cached_property
    def by_identifier(self) -> dict[tuple[str, str, str], set[int]]:
        """Contributions par (type d'identifiant, patronyme, identifiant) de leurs contributions sources."""
        by_identifier: dict[tuple[str, str, str], set[int]] = defaultdict(set)
        for g in self.contributions:
            for m in self._members(g):
                if m.last_name and m.orcid:
                    by_identifier[("orcid", m.last_name, m.orcid)].add(g.index)
                if m.last_name and m.idref:
                    by_identifier[("idref", m.last_name, m.idref)].add(g.index)
        return by_identifier

    def shared_identifier(self, record_contributions: Sequence[SourceContribution]) -> None:
        """Lie une contribution source à la contribution dont une autre contribution source partage son ORCID ou son IdRef, à patronyme égal. Un identifiant présent dans plusieurs contributions ne lie rien."""
        for s in record_contributions:
            if s.id in self.links or not s.last_name or not (s.orcid or s.idref):
                continue
            candidates = (
                self.by_identifier.get(("orcid", s.last_name, s.orcid), set()) if s.orcid else set()
            )
            if not candidates and s.idref:
                candidates = self.by_identifier.get(("idref", s.last_name, s.idref), set())
            if len(candidates) == 1 and (index := next(iter(candidates))) not in self.taken:
                self.link(s, self.by_index[index], GroupingMethod.IDENTIFIER)

    def name_steps(self) -> None:
        """Noms puis identifiants, sur les contributions sources et les contributions sans lien."""
        record_contributions = [s for s in self.record_contributions if s.id not in self.links]
        for key in (_name_key, _full_name_key, _initial_key):
            self.unique_pairs(key, record_contributions)
        self.shared_identifier(record_contributions)

    def _in_order(self, s: SourceContribution) -> bool:
        """Le lien de `s` entre dans le filtre d'ordre : la contribution a une position, et le lien ne vient pas d'un identifiant."""
        return self.links[s.id] in self.ranked and self.methods[s.id] != GroupingMethod.IDENTIFIER

    def order_filter(self) -> None:
        """Garde la plus longue suite de liens rangés dans le même ordre des deux côtés ; écarte et interdit les autres. Un lien par identifiant, ou d'une contribution source ou d'une contribution sans position, reste."""
        ordered = [
            (s.position, self.rank[self.links[s.id]], s.id)
            for s in self.record_contributions
            if s.id in self.links and s.position is not None and self._in_order(s)
        ]
        kept = longest_ordered(ordered)
        for _, _, source_contribution_id in ordered:
            if source_contribution_id not in kept:
                self.unlink(source_contribution_id)

    def gaps(self) -> tuple[dict[int, int], dict[int, int]]:
        """Trou de chaque contribution source et de chaque contribution restées sans lien, parmi celles qui ont une position."""
        anchor_positions = sorted(
            s.position
            for s in self.record_contributions
            if s.id in self.links and s.position is not None
        )
        anchor_ranks = sorted(self.rank[g] for g in self.taken if g in self.ranked)
        source_contribution_gaps = {
            s.id: gap(anchor_positions, s.position)
            for s in self.record_contributions
            if s.id not in self.links and s.position is not None
        }
        contribution_gaps = {
            g.index: gap(anchor_ranks, self.rank[g.index])
            for g in self.contributions
            if g.index not in self.taken and g.index in self.ranked
        }
        return source_contribution_gaps, contribution_gaps

    def order_in_gaps(self) -> None:
        """Dans chaque trou, patronyme et initiale en nombre égal des deux côtés : lien dans l'ordre des positions."""
        source_contribution_gaps, contribution_gaps = self.gaps()
        by_source_contribution: dict[tuple[str, str, int], list[SourceContribution]] = {}
        by_contribution: dict[tuple[str, str, int], list[Contribution]] = {}
        for s in self.record_contributions:
            if s.id in source_contribution_gaps and s.last_name:
                by_source_contribution.setdefault(
                    (s.last_name, s.first_name[:1], source_contribution_gaps[s.id]), []
                ).append(s)
        for g in self.contributions:
            if g.index in contribution_gaps and g.reference.last_name:
                ref = g.reference
                key = (ref.last_name, ref.first_name[:1], contribution_gaps[g.index])
                by_contribution.setdefault(key, []).append(g)
        for k, ss in by_source_contribution.items():
            gs = by_contribution.get(k, [])
            if len(ss) == len(gs):
                for s, g in zip(ss, gs, strict=True):
                    self.link(s, g, GroupingMethod.ORDER)

    def resolve(
        self,
        source_record_id: int,
        *,
        model: ResidualModel | None = None,
        assign: Assign | None = None,
        on_residual: ResidualSink | None = None,
    ) -> dict[int, _Link]:
        """Liens des contributions sources de l'enregistrement source vers les contributions : noms et identifiants, filtre d'ordre deux fois, ordre dans les trous, puis le résidu par le modèle quand `model` et `assign` sont donnés. `on_residual` reçoit le résidu de la règle, avant le modèle."""
        self.name_steps()
        self.order_filter()
        self.name_steps()
        self.order_filter()
        self.order_in_gaps()
        if on_residual is not None:
            source_contribution_gaps, contribution_gaps = self.gaps()
            on_residual(
                source_record_id,
                [
                    _author(s, source_contribution_gaps[s.id])
                    for s in self.record_contributions
                    if s.id in source_contribution_gaps
                ],
                [
                    _author(g.reference, contribution_gaps[g.index])
                    for g in self.contributions
                    if g.index in contribution_gaps
                ],
            )
        links = {s: _Link(g, self.methods[s]) for s, g in self.links.items()}
        if model is not None and assign is not None:
            residual = _residual_links(self, self.source_contributions, model, assign)
            for source_contribution_id, (g, score, margin) in residual.items():
                links[source_contribution_id] = _Link(g, GroupingMethod.MODEL, score, margin)
        return links


class _Link(NamedTuple):
    """Lien d'une contribution source vers la contribution d'indice `group`, avec le score et la marge d'un lien du modèle."""

    contribution: int
    method: GroupingMethod
    score: float | None = None
    margin: float | None = None


def _author(s: SourceContribution, gap_index: int) -> Author:
    return Author(s.last_name, s.first_name, s.orcid, s.idref, gap_index)


def _swapped(s: SourceContribution) -> SourceContribution:
    return replace(s, last_name=s.first_name, first_name=s.last_name)


def _inverted(
    record_contributions: Sequence[SourceContribution], contributions: Sequence[Contribution]
) -> bool:
    """L'enregistrement source donne le prénom à la place du patronyme : plus de ses prénoms que de ses patronymes sont des patronymes de contributions."""
    last_names = {g.reference.last_name for g in contributions if g.reference.last_name}
    direct = sum(s.last_name in last_names for s in record_contributions)
    swapped = sum(bool(s.first_name) and s.first_name in last_names for s in record_contributions)
    return swapped > direct


def _residual_links(
    record_links: _SourceRecordLinks,
    source_contributions: Mapping[int, SourceContribution],
    model: ResidualModel,
    assign: Assign,
) -> dict[int, tuple[int, float, float]]:
    """Liens du résidu : contribution source → (indice de contribution, score, marge).

    Une paire candidate partage un trou ou un trou voisin, les deux premières lettres du patronyme, ou un identifiant. Son score est le meilleur face aux contributions sources de la contribution retenus : ceux que la position seule ne rapproche pas (`position_only`), et dont les initiales ne contredisent pas un patronyme seulement proche (`conflicting_initials`). Un lien est retenu quand le score dépasse `link_threshold` du nombre de contributions restants.
    """
    source_contribution_gaps, contribution_gaps = record_links.gaps()
    rest_source_contributions = [
        s for s in record_links.record_contributions if s.id in source_contribution_gaps
    ]
    rest_contributions = [g for g in record_links.contributions if g.index in contribution_gaps]
    if not rest_source_contributions or not rest_contributions:
        return {}
    threshold = link_threshold(len(rest_contributions))
    members = {
        g.index: [
            _author(source_contributions[m.source_contribution], contribution_gaps[g.index])
            for m in g.members
        ]
        for g in rest_contributions
    }
    # Index de blocage : contributions par trou, par deux premières lettres d'un patronyme de contribution source, par identifiant de contribution source.
    by_gap: dict[int, set[int]] = defaultdict(set)
    by_prefix: dict[str, set[int]] = defaultdict(set)
    by_orcid: dict[str, set[int]] = defaultdict(set)
    by_idref: dict[str, set[int]] = defaultdict(set)
    for index, authors in members.items():
        by_gap[contribution_gaps[index]].add(index)
        for y in authors:
            by_prefix[y.last_name[:2]].add(index)
            if y.orcid:
                by_orcid[y.orcid].add(index)
            if y.idref:
                by_idref[y.idref].add(index)
    gains: dict[tuple[int, int], float] = {}
    for s in rest_source_contributions:
        x = _author(s, source_contribution_gaps[s.id])
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
                and not _conflicting_initials(x, y, levels)
            ]
            # Le blocage ne retient que les contributions sources retenues ; le trou est celui de la contribution.
            if not kept or not (
                abs(x.gap - contribution_gaps[index]) <= 1
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
) -> list[Contribution]:
    """Contributions d'une publication.

    Les enregistrements sources se traitent du plus long au plus court, chacun face aux contributions déjà formées. À longueur égale, les enregistrements sources `deferred` passent après les autres, puis l'ordre suit leur identifiant. Un enregistrement source qui intervertit patronyme et prénom (`_inverted`) s'aligne avec ses noms remis dans l'ordre. `model` et `assign` lient en plus le résidu. `on_residual` reçoit le résidu de la règle, avant le modèle.
    """
    source_contributions = {
        s.id: s for record_contributions in source_records.values() for s in record_contributions
    }
    contributions: list[Contribution] = []
    order = sorted(source_records, key=lambda n: (-len(source_records[n]), n in deferred, n))
    for i, source_record_id in enumerate(order):
        record_contributions = sorted(source_records[source_record_id], key=_list_order)
        if i and _inverted(record_contributions, contributions):
            record_contributions = [_swapped(s) for s in record_contributions]
            source_contributions.update((s.id, s) for s in record_contributions)
        links = (
            _SourceRecordLinks(record_contributions, contributions, source_contributions).resolve(
                source_record_id, model=model, assign=assign, on_residual=on_residual
            )
            if i
            else {}
        )
        contributions = _with_new_contributions(
            contributions, record_contributions, links, source_record_id
        )
    return contributions


def _with_new_contributions(
    contributions: Sequence[Contribution],
    record_contributions: Sequence[SourceContribution],
    links: Mapping[int, _Link],
    source_record_id: int,
) -> list[Contribution]:
    """Contributions rangées après l'alignement d'un enregistrement source : ses contributions sources liées rejoignent leur contribution, les autres fondent une contribution.

    Une contribution fondé se range juste après la contribution de la contribution source liée qui le précède dans la liste, ou en tête sans telle contribution source. Les contributions fondés sans position se rangent à la fin.
    """
    by_index = {g.index: g for g in contributions}
    following: dict[int | None, list[Contribution]] = defaultdict(list)
    unpositioned: list[Contribution] = []
    previous: int | None = None
    next_index = len(contributions)
    for s in record_contributions:
        if (link := links.get(s.id)) is not None:
            member = Member(s.id, source_record_id, link.method, link.score, link.margin)
            by_index[link.contribution].members.append(member)
            previous = link.contribution
        else:
            contribution = Contribution(
                next_index, s, [Member(s.id, source_record_id, GroupingMethod.REFERENCE)]
            )
            next_index += 1
            (unpositioned if s.position is None else following[previous]).append(contribution)
    return [
        *following[None],
        *(placed for g in contributions for placed in (g, *following[g.index])),
        *unpositioned,
    ]
