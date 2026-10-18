"""Groupes de signatures : les signatures d'un même auteur dans une publication, avec au maximum une signature par notice.

Les notices d'une publication se traitent de la plus longue liste d'auteurs à la plus courte, chacune face aux groupes déjà formés. Ce module réunit les décisions pures : ordre des liens, trous, poids du modèle du résidu, réconciliation des identifiants de groupes.
"""

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache


class GroupingMethod(StrEnum):
    """Origine de l'appartenance d'une signature à son groupe. Mappe l'enum PostgreSQL `grouping_method`."""

    REFERENCE = "reference"
    """La signature fonde le groupe."""
    NAME = "name"
    """Patronyme, prénom ou initiale, uniques de part et d'autre."""
    IDENTIFIER = "identifier"
    """ORCID ou IdRef partagé, à patronyme égal."""
    ORDER = "order"
    """Rang parmi les signatures de même patronyme et de même initiale."""
    MODEL = "model"
    """Modèle probabiliste, avec un score et une marge."""


def full_first_name(first_name: str) -> str:
    """Prénom complet, ou chaîne vide quand le prénom se réduit à des initiales."""
    return first_name if any(len(part) > 1 for part in first_name.split()) else ""


def longest_ordered(links: Iterable[tuple[int, int, int]]) -> set[int]:
    """Identifiants de la plus longue suite de liens (position dans la notice, rang du groupe, identifiant) dont les rangs croissent avec les positions."""
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
    """Ce qu'une signature ou un membre de groupe expose au modèle du résidu : noms normalisés, identifiants, trou."""

    last_name: str
    first_name: str
    orcid: str
    idref: str
    gap: int


@lru_cache(maxsize=1_000_000)
def _initials(first_name: str) -> str:
    return "".join(part[:1] for part in first_name.split())


@lru_cache(maxsize=1_000_000)
def _only_initials(first_name: str) -> bool:
    return all(len(part) <= 1 for part in first_name.split())


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
    elif jaro_winkler(lx, ly) >= 0.92:
        levels[Comparison.LAST_NAME] = ComparisonLevel.JW_092
    elif jaro_winkler(lx, ly) >= 0.8:
        levels[Comparison.LAST_NAME] = ComparisonLevel.JW_08
    else:
        levels[Comparison.LAST_NAME] = ComparisonLevel.ELSE
    fx, fy = x.first_name, y.first_name
    if not fx or not fy:
        levels[Comparison.FIRST_NAME] = None
    elif fx == fy:
        levels[Comparison.FIRST_NAME] = ComparisonLevel.FIRST_NAME_EXACT
    elif (_only_initials(fx) or _only_initials(fy)) and (
        _initials(fx).startswith(_initials(fy)) or _initials(fy).startswith(_initials(fx))
    ):
        levels[Comparison.FIRST_NAME] = ComparisonLevel.INITIALS_MATCH
    elif jaro_winkler(fx, fy) >= 0.9:
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

    Chaque nouveau groupe reprend l'identifiant de l'ancien groupe avec lequel il partage le plus de signatures, chaque ancien identifiant une seule fois, le plus petit en cas d'égalité. `old` : signatures de chaque ancien groupe ; `new` : signatures de chaque nouveau groupe.
    """
    owner = {sig: old_id for old_id, sigs in old.items() for sig in sigs}
    overlaps: list[tuple[int, int, int]] = []
    for index, sigs in enumerate(new):
        counts: dict[int, int] = {}
        for sig in sigs:
            if (old_id := owner.get(sig)) is not None:
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
class Signature:
    """Signature à grouper : notice, position dans la liste, noms normalisés, identifiants."""

    id: int
    notice: int
    position: int
    last_name: str
    first_name: str
    orcid: str = ""
    idref: str = ""


@dataclass(frozen=True)
class Member:
    """Appartenance d'une signature à un groupe ; `score` et `margin` en bits pour `GroupingMethod.MODEL`."""

    signature: int
    notice: int
    method: GroupingMethod
    score: float | None = None
    margin: float | None = None


@dataclass
class Group:
    """Groupe formé : sa signature de référence et ses membres."""

    index: int
    reference: Signature
    members: list[Member]


type Assign = Callable[[Sequence[Sequence[float]]], Iterable[tuple[int, int]]]
"""Affectation de gain maximal sur une matrice de gains : paires (ligne, colonne)."""

type ResidualSink = Callable[[int, Sequence[Author], Sequence[Author]], None]
"""Reçoit le résidu de la règle pour une notice : son identifiant, ses signatures sans lien, puis les signatures de référence des groupes sans lien, chacune avec son trou."""


def _name_key(s: Signature) -> str:
    return s.last_name


def _full_name_key(s: Signature) -> tuple[str, str] | None:
    full = full_first_name(s.first_name)
    return (s.last_name, full) if s.last_name and full else None


def _initial_key(s: Signature) -> tuple[str, str] | None:
    return (s.last_name, s.first_name[:1]) if s.last_name and s.first_name else None


class _NoticeLinks:
    """Liens de la règle entre une notice et les groupes déjà formés."""

    def __init__(self, sigs: Sequence[Signature], groups: Sequence[Group]) -> None:
        self.sigs = sigs
        self.groups = groups
        self.rank = {g.index: r for r, g in enumerate(groups)}
        self.links: dict[int, int] = {}
        self.methods: dict[int, GroupingMethod] = {}
        self.forbidden: set[tuple[int, int]] = set()

    def link(self, s: Signature, g: Group, method: GroupingMethod) -> None:
        if (s.id, g.index) not in self.forbidden:
            self.links[s.id] = g.index
            self.methods[s.id] = method

    def linked_groups(self) -> set[int]:
        return set(self.links.values())

    def unique_pairs(self, key: Callable[[Signature], object], method: GroupingMethod) -> None:
        """Lie une signature et un groupe quand leur clé est unique des deux côtés, parmi les signatures et groupes sans lien."""
        taken = self.linked_groups()
        by_sig: dict[object, list[Signature]] = {}
        by_group: dict[object, list[Group]] = {}
        for s in self.sigs:
            if s.id not in self.links and (k := key(s)):
                by_sig.setdefault(k, []).append(s)
        for g in self.groups:
            if g.index not in taken and (k := key(g.reference)):
                by_group.setdefault(k, []).append(g)
        for k, ss in by_sig.items():
            gs = by_group.get(k, [])
            if len(ss) == 1 and len(gs) == 1:
                self.link(ss[0], gs[0], method)

    def shared_identifier(self) -> None:
        """Lie une signature au groupe qui partage son ORCID ou son IdRef, à patronyme égal."""
        by_name: dict[str, list[Group]] = {}
        for g in self.groups:
            by_name.setdefault(g.reference.last_name, []).append(g)
        for s in self.sigs:
            if s.id in self.links or not s.last_name:
                continue
            taken = self.linked_groups()
            for g in by_name.get(s.last_name, ()):
                ref = g.reference
                if g.index not in taken and (
                    (s.orcid and s.orcid == ref.orcid) or (s.idref and s.idref == ref.idref)
                ):
                    self.link(s, g, GroupingMethod.IDENTIFIER)
                    if s.id in self.links:
                        break

    def name_steps(self) -> None:
        self.unique_pairs(_name_key, GroupingMethod.NAME)
        self.unique_pairs(_full_name_key, GroupingMethod.NAME)
        self.unique_pairs(_initial_key, GroupingMethod.NAME)
        self.shared_identifier()

    def order_filter(self) -> None:
        """Garde la plus longue suite de liens rangés dans le même ordre des deux côtés ; écarte et interdit les autres."""
        kept = longest_ordered(
            (s.position, self.rank[self.links[s.id]], s.id) for s in self.sigs if s.id in self.links
        )
        for s in self.sigs:
            if s.id in self.links and s.id not in kept:
                self.forbidden.add((s.id, self.links.pop(s.id)))
                del self.methods[s.id]

    def gaps(self) -> tuple[dict[int, int], dict[int, int]]:
        """Trou de chaque signature et de chaque groupe restés sans lien."""
        taken = self.linked_groups()
        anchor_positions = sorted(s.position for s in self.sigs if s.id in self.links)
        anchor_ranks = sorted(self.rank[g] for g in taken)
        sig_gaps = {
            s.id: gap(anchor_positions, s.position) for s in self.sigs if s.id not in self.links
        }
        group_gaps = {
            g.index: gap(anchor_ranks, self.rank[g.index])
            for g in self.groups
            if g.index not in taken
        }
        return sig_gaps, group_gaps

    def order_in_gaps(self) -> None:
        """Dans chaque trou, patronyme et initiale en nombre égal des deux côtés : lien dans l'ordre des positions."""
        sig_gaps, group_gaps = self.gaps()
        by_sig: dict[tuple[str, str, int], list[Signature]] = {}
        by_group: dict[tuple[str, str, int], list[Group]] = {}
        for s in self.sigs:
            if s.id in sig_gaps and s.last_name:
                by_sig.setdefault((s.last_name, s.first_name[:1], sig_gaps[s.id]), []).append(s)
        for g in self.groups:
            if g.index in group_gaps and g.reference.last_name:
                ref = g.reference
                key = (ref.last_name, ref.first_name[:1], group_gaps[g.index])
                by_group.setdefault(key, []).append(g)
        for k, ss in by_sig.items():
            gs = by_group.get(k, [])
            if len(ss) > 1 and len(ss) == len(gs):
                for s, g in zip(ss, gs, strict=True):
                    self.link(s, g, GroupingMethod.ORDER)


def _author(s: Signature, gap_index: int) -> Author:
    return Author(s.last_name, s.first_name, s.orcid, s.idref, gap_index)


def _swapped(s: Signature) -> Signature:
    return replace(s, last_name=s.first_name, first_name=s.last_name)


def _inverted(sigs: Sequence[Signature], groups: Sequence[Group]) -> bool:
    """La notice donne le prénom à la place du patronyme : plus de ses prénoms que de ses patronymes sont des patronymes de groupes."""
    last_names = {g.reference.last_name for g in groups if g.reference.last_name}
    direct = sum(s.last_name in last_names for s in sigs)
    swapped = sum(bool(s.first_name) and s.first_name in last_names for s in sigs)
    return swapped > direct


def _residual_links(
    notice: _NoticeLinks, signatures: Mapping[int, Signature], model: ResidualModel, assign: Assign
) -> dict[int, tuple[int, float, float]]:
    """Liens du résidu : signature → (indice de groupe, score, marge).

    Une paire candidate partage un trou ou un trou voisin, les deux premières lettres du patronyme, ou un identifiant. Son score est le meilleur face aux membres du groupe que la position seule ne rapproche pas (`position_only`). Un lien est retenu quand le score dépasse `link_threshold` du nombre de groupes restants.
    """
    sig_gaps, group_gaps = notice.gaps()
    rest_sigs = [s for s in notice.sigs if s.id in sig_gaps]
    rest_groups = [g for g in notice.groups if g.index in group_gaps]
    if not rest_sigs or not rest_groups:
        return {}
    threshold = link_threshold(len(rest_groups))
    members = {
        g.index: [_author(signatures[m.signature], group_gaps[g.index]) for m in g.members]
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
    for s in rest_sigs:
        x = _author(s, sig_gaps[s.id])
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
    notices: Mapping[int, Sequence[Signature]],
    *,
    ordered: bool = True,
    model: ResidualModel | None = None,
    assign: Assign | None = None,
    on_residual: ResidualSink | None = None,
    deferred: Collection[int] = (),
) -> list[Group]:
    """Groupes de signatures d'une publication.

    Les notices se traitent de la plus longue à la plus courte, chacune face aux groupes déjà formés. À longueur égale, les notices `deferred` passent après les autres, puis l'ordre suit l'identifiant de notice. Une notice qui intervertit patronyme et prénom (`_inverted`) s'aligne avec ses noms remis dans l'ordre. `ordered` applique le filtre d'ordre et l'ordre dans les trous, pour des signatures aux positions significatives. `model` et `assign` lient en plus le résidu. `on_residual` reçoit le résidu de la règle, avant le modèle.
    """
    signatures = {s.id: s for sigs in notices.values() for s in sigs}
    groups: list[Group] = []
    order = sorted(notices, key=lambda n: (-len(notices[n]), n in deferred, n))
    for i, notice_id in enumerate(order):
        sigs = sorted(notices[notice_id], key=lambda s: (s.position, s.id))
        if i and _inverted(sigs, groups):
            sigs = [_swapped(s) for s in sigs]
            signatures.update((s.id, s) for s in sigs)
        links: dict[int, int] = {}
        methods: dict[int, GroupingMethod] = {}
        scores: dict[int, tuple[float, float]] = {}
        if i:
            notice = _NoticeLinks(sigs, groups)
            notice.name_steps()
            if ordered:
                notice.order_filter()
                notice.name_steps()
                notice.order_filter()
                notice.order_in_gaps()
                if on_residual is not None:
                    sig_gaps, group_gaps = notice.gaps()
                    on_residual(
                        notice_id,
                        [_author(s, sig_gaps[s.id]) for s in sigs if s.id in sig_gaps],
                        [
                            _author(g.reference, group_gaps[g.index])
                            for g in groups
                            if g.index in group_gaps
                        ],
                    )
                if model is not None and assign is not None:
                    residual = _residual_links(notice, signatures, model, assign)
                    for sig, (g, link_score, link_margin) in residual.items():
                        notice.links[sig] = g
                        notice.methods[sig] = GroupingMethod.MODEL
                        scores[sig] = (link_score, link_margin)
            links, methods = notice.links, notice.methods
        by_index = {g.index: g for g in groups}
        for s in sigs:
            if s.id in links:
                score, margin = scores.get(s.id, (None, None))
                member = Member(s.id, notice_id, methods[s.id], score, margin)
                by_index[links[s.id]].members.append(member)
            else:
                member = Member(s.id, notice_id, GroupingMethod.REFERENCE)
                groups.append(Group(len(groups), s, [member]))
        groups.sort(key=lambda g: (g.reference.position, g.index))
    return groups
