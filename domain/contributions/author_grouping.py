"""Alignement des auteurs d'une publication : les contributions sources d'un même auteur forment une contribution, avec au plus une contribution source par enregistrement source.

Les liens se font par le nom, par identifiant, puis par la position dans la liste des auteurs. Une contribution source sans lien se situe par son trou : l'intervalle entre deux liens consécutifs de la liste. Un modèle probabiliste lie ce qui reste, le résidu.
"""

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import cached_property, lru_cache
from typing import NamedTuple

from domain.persons.name_matching import (
    first_name_initials,
    full_first_name_extends,
    is_full_first_name,
    is_initials,
)


class GroupingMethod(StrEnum):
    """Origine de l'appartenance d'une contribution source à sa contribution. Reflet du type PostgreSQL `grouping_method`."""

    REFERENCE = "reference"
    """La contribution source fonde la contribution."""
    NAME = "name"
    """Nom de famille, prénom ou initiale, uniques de part et d'autre."""
    IDENTIFIER = "identifier"
    """ORCID ou IdRef partagé, à nom de famille égal."""
    ORDER = "order"
    """Rang parmi les contributions sources de même nom de famille et de même initiale."""
    MODEL = "model"
    """Modèle probabiliste, avec un score et une marge."""


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


def _longest_ordered(links: Iterable[tuple[int, int, int]]) -> set[int]:
    """Renvoie les identifiants de la plus longue suite de liens (position dans l'enregistrement source, rang de la contribution, identifiant) dont les rangs croissent avec les positions."""
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


@lru_cache(maxsize=1_000_000)
def _jaro_winkler(a: str, b: str) -> float:
    """Calcule la similarité de Jaro-Winkler, comme `jaro_winkler_similarity` de DuckDB : demi-transpositions arrondies à l'entier inférieur ; bonus de préfixe au-delà de 0,7, sur 4 caractères au plus, facteur 0,1."""
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
    """Contribution source vue par le modèle du résidu."""

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
    ELSE = "else"
    """Aucun des niveaux de ressemblance de la comparaison."""


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
    """Renvoie le niveau de chaque comparaison du modèle du résidu entre deux auteurs ; `None` quand une valeur manque."""
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
    elif _jaro_winkler(lx, ly) >= _JW_092:
        levels[Comparison.LAST_NAME] = ComparisonLevel.JW_092
    elif _jaro_winkler(lx, ly) >= _JW_08:
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
    elif _jaro_winkler(fx, fy) >= _JW_09:
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


def _position_only(levels: Mapping[Comparison, ComparisonLevel | None]) -> bool:
    """Vrai si seule la position relie deux auteurs, d'après leurs niveaux de comparaison (`comparison_levels`) : noms de famille sans ressemblance, prénoms sans ressemblance ou absents, aucun identifiant commun."""
    return (
        levels[Comparison.LAST_NAME] == ComparisonLevel.ELSE
        and levels[Comparison.FIRST_NAME] in (ComparisonLevel.ELSE, None)
        and not _shared_identifier(levels)
    )


def _conflicting_initials(
    x: Author, y: Author, levels: Mapping[Comparison, ComparisonLevel | None]
) -> bool:
    """Vrai pour des noms de famille seulement proches et des premières initiales différentes, sans identifiant commun : « V. Balakrishnan » et « S. Balaji ». `levels` : niveaux de comparaison des deux auteurs (`comparison_levels`)."""
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


type Assign = Callable[[Sequence[Sequence[float]]], Iterable[tuple[int, int]]]
"""Affectation de gain maximal sur une matrice de gains : paires (ligne, colonne)."""


@dataclass(frozen=True)
class ResidualModel:
    """Modèle qui lie le résidu de la règle."""

    weights: Mapping[str, Mapping[str, float]]
    """Poids en bits de chaque niveau de comparaison."""
    assign: Assign
    """Affecte les contributions sources du résidu aux contributions d'après la matrice des gains."""

    def score_levels(self, levels: Mapping[Comparison, ComparisonLevel | None]) -> float:
        """Renvoie la somme des poids des niveaux de comparaison de deux auteurs (`comparison_levels`), sans a priori."""
        return sum(
            self.weights[name].get(level, 0.0)
            for name, level in levels.items()
            if level is not None
        )


def _link_threshold(candidate_contributions: int) -> float:
    """Renvoie le score au-delà duquel un lien du résidu est retenu : log2 du nombre de contributions candidates. Avec un a priori de 1 sur ce nombre, ce score donne une probabilité supérieure à 1/2."""
    return math.log2(max(candidate_contributions, 2))


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
    orcid: str = ""
    idref: str = ""


@dataclass(frozen=True)
class Member:
    """Appartenance d'une contribution source à une contribution."""

    source_contribution: int
    source_record: int
    method: GroupingMethod
    score: float | None = None
    """Score en bits, pour `GroupingMethod.MODEL`."""
    margin: float | None = None
    """Marge en bits, pour `GroupingMethod.MODEL`."""


@dataclass(eq=False)
class Contribution:
    """Contribution formée : sa contribution source de référence et ses contributions sources."""

    reference: SourceContribution
    members: list[Member]


type ResidualSink = Callable[[int, Sequence[Author], Sequence[Author]], None]
"""Reçoit le résidu de la règle pour un enregistrement source : son identifiant, ses contributions sources sans lien, puis les contributions sources de référence des contributions sans lien, chacune avec son trou."""


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


def _swapped_full_name_key(s: SourceContribution) -> tuple[str, str] | None:
    return _full_name_key(_swapped(s))


def _swapped_initial_key(s: SourceContribution) -> tuple[str, str] | None:
    return _initial_key(_swapped(s))


_SWAPPED_KEYS = (
    (_full_name_key, _swapped_full_name_key),
    (_initial_key, _swapped_initial_key),
)
"""Clé d'une contribution source, et clé de la même forme sur une référence aux nom de famille et prénom intervertis."""


class _Link(NamedTuple):
    """Lien d'une contribution source vers une contribution, avec le score et la marge d'un lien du modèle."""

    contribution: Contribution
    method: GroupingMethod
    score: float | None = None
    margin: float | None = None
    swapped_reference: bool = False
    """Le lien se fait face à la référence aux nom de famille et prénom intervertis."""


class _SourceRecordLinks:
    """Liens de la règle entre un enregistrement source et les contributions déjà formées.

    Seules les contributions sources et les contributions qui ont une position entrent dans le filtre d'ordre, les trous et le résidu. Les autres se lient par le nom et l'identifiant.
    """

    def __init__(
        self,
        record_contributions: Sequence[SourceContribution],
        contributions: Sequence[Contribution],
        source_contributions: Mapping[int, SourceContribution],
    ) -> None:
        self.record_contributions = record_contributions
        self.contributions = contributions
        # Toutes les contributions sources par identifiant : les identifiants se comparent à tous les membres d'une contribution.
        self.source_contributions = source_contributions
        self.rank = {g: r for r, g in enumerate(contributions)}
        self.ranked = {g for g in contributions if g.reference.position is not None}
        self.links: dict[int, _Link] = {}
        # Contributions liées : une contribution reçoit au plus un lien.
        self.taken: set[Contribution] = set()
        self.forbidden: set[tuple[int, Contribution]] = set()
        self._contribution_indexes: dict[
            Callable[[SourceContribution], object], dict[object, list[Contribution]]
        ] = {}

    def link(
        self,
        s: SourceContribution,
        g: Contribution,
        method: GroupingMethod,
        *,
        swapped_reference: bool = False,
    ) -> None:
        """Lie la contribution source à la contribution, sauf paire interdite."""
        if (s.id, g) not in self.forbidden:
            self.links[s.id] = _Link(g, method, swapped_reference=swapped_reference)
            self.taken.add(g)

    def unlink(self, source_contribution_id: int) -> None:
        """Retire le lien de la contribution source et l'interdit."""
        g = self.links.pop(source_contribution_id).contribution
        self.taken.discard(g)
        self.forbidden.add((source_contribution_id, g))

    def _contributions_by(
        self, key: Callable[[SourceContribution], object]
    ) -> dict[object, list[Contribution]]:
        """Renvoie les contributions par clé de leur contribution source de référence."""
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
        record_contributions: Sequence[SourceContribution],
        key: Callable[[SourceContribution], object],
        reference_key: Callable[[SourceContribution], object],
        *,
        swapped: bool = False,
    ) -> None:
        """Lie une contribution source et une contribution de même clé. La clé est unique des deux côtés : parmi les contributions sources données, et parmi les références des contributions restées sans lien.

        Args:
            swapped: la clé de la référence porte sur ses nom de famille et prénom intervertis. La contribution source se lie seulement si son nom de famille est absent des références sans lien.
        """
        by_source_contribution: dict[object, list[SourceContribution]] = {}
        for s in record_contributions:
            if s.id not in self.links and (k := key(s)):
                by_source_contribution.setdefault(k, []).append(s)
        by_reference = self._contributions_by(reference_key)
        by_last_name = self._contributions_by(_name_key)
        for k, ss in by_source_contribution.items():
            if len(ss) != 1:
                continue
            s = ss[0]
            if swapped and any(g not in self.taken for g in by_last_name.get(s.last_name, [])):
                continue
            gs = [g for g in by_reference.get(k, []) if g not in self.taken]
            if len(gs) == 1:
                self.link(s, gs[0], GroupingMethod.NAME, swapped_reference=swapped)

    @cached_property
    def by_identifier(self) -> dict[tuple[str, str, str], set[Contribution]]:
        """Contributions par (type d'identifiant, nom de famille, identifiant) de leurs contributions sources."""
        by_identifier: dict[tuple[str, str, str], set[Contribution]] = defaultdict(set)
        for g in self.contributions:
            for m in g.members:
                s = self.source_contributions[m.source_contribution]
                if s.last_name and s.orcid:
                    by_identifier[("orcid", s.last_name, s.orcid)].add(g)
                if s.last_name and s.idref:
                    by_identifier[("idref", s.last_name, s.idref)].add(g)
        return by_identifier

    def shared_identifier(self, record_contributions: Sequence[SourceContribution]) -> None:
        """Lie une contribution source à la contribution dont une autre contribution source partage son ORCID ou son IdRef, à nom de famille égal. Un identifiant présent dans plusieurs contributions ne lie rien."""
        for s in record_contributions:
            if s.id in self.links or not s.last_name or not (s.orcid or s.idref):
                continue
            candidates = (
                self.by_identifier.get(("orcid", s.last_name, s.orcid), set()) if s.orcid else set()
            )
            if not candidates and s.idref:
                candidates = self.by_identifier.get(("idref", s.last_name, s.idref), set())
            if len(candidates) == 1 and (g := next(iter(candidates))) not in self.taken:
                self.link(s, g, GroupingMethod.IDENTIFIER)

    def name_steps(self) -> None:
        """Lie les contributions sources et les contributions sans lien : par les noms, par les noms face aux références interverties, puis par les identifiants."""
        record_contributions = [s for s in self.record_contributions if s.id not in self.links]
        for key in (_name_key, _full_name_key, _initial_key):
            self.unique_pairs(record_contributions, key, key)
        for key, swapped_key in _SWAPPED_KEYS:
            self.unique_pairs(record_contributions, key, swapped_key, swapped=True)
        self.shared_identifier(record_contributions)

    def _in_order(self, s: SourceContribution) -> bool:
        """Vrai si le lien de `s` entre dans le filtre d'ordre : la contribution a une position, et le lien ne vient pas d'un identifiant."""
        link = self.links[s.id]
        return link.contribution in self.ranked and link.method != GroupingMethod.IDENTIFIER

    def order_filter(self) -> None:
        """Garde la plus longue suite de liens rangés dans le même ordre des deux côtés ; écarte et interdit les autres. Un lien par identifiant, ou d'une contribution source ou d'une contribution sans position, reste."""
        ordered = [
            (s.position, self.rank[self.links[s.id].contribution], s.id)
            for s in self.record_contributions
            if s.id in self.links and s.position is not None and self._in_order(s)
        ]
        kept = _longest_ordered(ordered)
        for _, _, source_contribution_id in ordered:
            if source_contribution_id not in kept:
                self.unlink(source_contribution_id)

    def gaps(self) -> tuple[dict[int, int], dict[Contribution, int]]:
        """Renvoie le trou de chaque contribution source et de chaque contribution restées sans lien, parmi celles qui ont une position. Le trou est le nombre de liens qui la précèdent dans sa liste."""
        anchor_positions = sorted(
            s.position
            for s in self.record_contributions
            if s.id in self.links and s.position is not None
        )
        anchor_ranks = sorted(self.rank[g] for g in self.taken if g in self.ranked)
        source_contribution_gaps = {
            s.id: bisect_left(anchor_positions, s.position)
            for s in self.record_contributions
            if s.id not in self.links and s.position is not None
        }
        contribution_gaps = {
            g: bisect_left(anchor_ranks, self.rank[g])
            for g in self.contributions
            if g not in self.taken and g in self.ranked
        }
        return source_contribution_gaps, contribution_gaps

    def order_in_gaps(self) -> None:
        """Lie dans l'ordre des positions, dans chaque trou, les contributions sources et les contributions de même nom de famille et initiale, en nombre égal des deux côtés."""
        source_contribution_gaps, contribution_gaps = self.gaps()
        by_source_contribution: dict[tuple[str, str, int], list[SourceContribution]] = {}
        by_contribution: dict[tuple[str, str, int], list[Contribution]] = {}
        for s in self.record_contributions:
            if s.id in source_contribution_gaps and s.last_name:
                by_source_contribution.setdefault(
                    (s.last_name, s.first_name[:1], source_contribution_gaps[s.id]), []
                ).append(s)
        for g in self.contributions:
            if g in contribution_gaps and g.reference.last_name:
                ref = g.reference
                key = (ref.last_name, ref.first_name[:1], contribution_gaps[g])
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
        on_residual: ResidualSink | None = None,
    ) -> dict[int, _Link]:
        """Renvoie les liens des contributions sources de l'enregistrement source vers les contributions : noms et identifiants, filtre d'ordre deux fois, ordre dans les trous, puis le résidu par `model`.

        Args:
            on_residual: reçoit le résidu de la règle, avant le modèle.
        """
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
                    _author(g.reference, contribution_gaps[g])
                    for g in self.contributions
                    if g in contribution_gaps
                ],
            )
        links = dict(self.links)
        if model is not None:
            links.update(self._residual_links(model))
        return links

    def _residual_links(self, model: ResidualModel) -> dict[int, _Link]:
        """Calcule les liens du résidu par le modèle.

        Une paire candidate partage un trou ou un trou voisin, les deux premières lettres du nom de famille, ou un identifiant. Son score est le meilleur face aux contributions sources retenues de la contribution : celles reliées par plus que leur position (`_position_only`), sans initiales contredisant un nom de famille seulement proche (`_conflicting_initials`). Un lien est retenu si le score dépasse `_link_threshold` du nombre de contributions restantes.
        """
        source_contribution_gaps, contribution_gaps = self.gaps()
        rest_source_contributions = [
            s for s in self.record_contributions if s.id in source_contribution_gaps
        ]
        rest_contributions = [g for g in self.contributions if g in contribution_gaps]
        if not rest_source_contributions or not rest_contributions:
            return {}
        threshold = _link_threshold(len(rest_contributions))
        members = {
            g: [
                _author(self.source_contributions[m.source_contribution], contribution_gaps[g])
                for m in g.members
            ]
            for g in rest_contributions
        }
        # Index de blocage : contributions par trou, par deux premières lettres d'un nom de famille de contribution source, par identifiant de contribution source.
        by_gap: dict[int, set[Contribution]] = defaultdict(set)
        by_prefix: dict[str, set[Contribution]] = defaultdict(set)
        by_orcid: dict[str, set[Contribution]] = defaultdict(set)
        by_idref: dict[str, set[Contribution]] = defaultdict(set)
        for g, authors in members.items():
            by_gap[contribution_gaps[g]].add(g)
            for y in authors:
                by_prefix[y.last_name[:2]].add(g)
                if y.orcid:
                    by_orcid[y.orcid].add(g)
                if y.idref:
                    by_idref[y.idref].add(g)
        gains: dict[tuple[int, Contribution], float] = {}
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
            for g in candidates:
                kept = [
                    (y, levels)
                    for y in members[g]
                    if not _position_only(levels := comparison_levels(x, y))
                    and not _conflicting_initials(x, y, levels)
                ]
                # Le blocage s'applique seulement aux contributions sources retenues ; le trou est celui de la contribution.
                if not kept or not (
                    abs(x.gap - contribution_gaps[g]) <= 1
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
                    gains[(s.id, g)] = gain
        if not gains:
            return {}
        rows = sorted({s for s, _ in gains})
        cols = sorted({g for _, g in gains}, key=self.rank.__getitem__)
        matrix = [[gains.get((s, g), 0.0) for g in cols] for s in rows]
        out: dict[int, _Link] = {}
        for i, j in model.assign(matrix):
            gain = matrix[i][j]
            if gain <= 0:
                continue
            others = [matrix[i][c] for c in range(len(cols)) if c != j]
            others += [matrix[r][j] for r in range(len(rows)) if r != i]
            out[rows[i]] = _Link(
                cols[j], GroupingMethod.MODEL, gain + threshold, gain - max(others, default=0.0)
            )
        return out


def _author(s: SourceContribution, gap_index: int) -> Author:
    return Author(s.last_name, s.first_name, s.orcid, s.idref, gap_index)


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
    model: ResidualModel | None = None,
    on_residual: ResidualSink | None = None,
    deferred: Collection[int] = (),
) -> list[Contribution]:
    """Aligne les auteurs d'une publication, et renvoie ses contributions.

    Les enregistrements sources se traitent du plus long au plus court, chacun face aux contributions déjà formées. À longueur égale, les enregistrements sources `deferred` passent après les autres, puis l'ordre suit leur identifiant. Un enregistrement source qui intervertit nom de famille et prénom (`_inverted`) s'aligne avec ses noms remis dans l'ordre. Une référence liée à une contribution source par ses nom de famille et prénom intervertis prend l'ordre de la contribution source.

    Args:
        model: lie en plus le résidu.
        on_residual: reçoit le résidu de la règle, avant le modèle.
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
                source_record_id, model=model, on_residual=on_residual
            )
            if i
            else {}
        )
        for link in links.values():
            if link.swapped_reference:
                g = link.contribution
                g.reference = _swapped(g.reference)
                source_contributions[g.reference.id] = g.reference
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
    """Range les contributions après l'alignement d'un enregistrement source : ses contributions sources liées rejoignent leur contribution, les autres fondent une contribution.

    Une contribution fondée se range juste après la contribution de la dernière contribution source liée qui précède sa fondatrice dans la liste, ou en tête. Les contributions fondées sans position se rangent à la fin.
    """
    following: dict[Contribution | None, list[Contribution]] = defaultdict(list)
    unpositioned: list[Contribution] = []
    previous: Contribution | None = None
    for s in record_contributions:
        if (link := links.get(s.id)) is not None:
            member = Member(s.id, source_record_id, link.method, link.score, link.margin)
            link.contribution.members.append(member)
            previous = link.contribution
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
