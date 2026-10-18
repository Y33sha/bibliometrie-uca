"""Groupes de signatures : les signatures d'un même auteur dans une publication, avec au maximum une signature par notice.

Les notices d'une publication se traitent de la plus longue liste d'auteurs à la plus courte, chacune face aux groupes déjà formés. Ce module réunit les décisions pures : ordre des liens, trous, poids du modèle du résidu, réconciliation des identifiants de groupes.
"""

import math
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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


def _initials(first_name: str) -> str:
    return "".join(part[:1] for part in first_name.split())


def _only_initials(first_name: str) -> bool:
    return all(len(part) <= 1 for part in first_name.split())


def comparison_levels(x: Author, y: Author) -> dict[str, str | None]:
    """Niveau de chaque comparaison du modèle du résidu entre deux auteurs ; `None` quand une valeur manque."""
    levels: dict[str, str | None] = {}
    lx, ly = x.last_name, y.last_name
    if not lx or not ly:
        levels["ln"] = None
    elif lx == ly:
        levels["ln"] = "Exact match on ln"
    elif lx == y.first_name and ly == x.first_name:
        levels["ln"] = "reversed"
    elif set(lx.split()) <= set(ly.split()) or set(ly.split()) <= set(lx.split()):
        levels["ln"] = "mots inclus"
    elif jaro_winkler(lx, ly) >= 0.92:
        levels["ln"] = "jw 0.92"
    elif jaro_winkler(lx, ly) >= 0.8:
        levels["ln"] = "jw 0.8"
    else:
        levels["ln"] = "else"
    fx, fy = x.first_name, y.first_name
    if not fx or not fy:
        levels["fn"] = None
    elif fx == fy:
        levels["fn"] = "Exact match on fn"
    elif (_only_initials(fx) or _only_initials(fy)) and (
        _initials(fx).startswith(_initials(fy)) or _initials(fy).startswith(_initials(fx))
    ):
        levels["fn"] = "initiales concordantes"
    elif jaro_winkler(fx, fy) >= 0.9:
        levels["fn"] = "jw 0.9"
    else:
        levels["fn"] = "else"
    for name, vx, vy in (("orcid", x.orcid, y.orcid), ("idref", x.idref, y.idref)):
        levels[name] = None if not vx or not vy else ("exact" if vx == vy else "else")
    distance = abs(x.gap - y.gap)
    levels["gap"] = (
        "même trou" if distance == 0 else ("trou voisin" if distance == 1 else "ailleurs")
    )
    return levels


@dataclass(frozen=True)
class ResidualModel:
    """Poids en bits de chaque niveau de comparaison du modèle du résidu."""

    weights: Mapping[str, Mapping[str, float]]

    def score(self, x: Author, y: Author) -> float:
        """Somme des poids des comparaisons entre deux auteurs, sans a priori."""
        return sum(
            self.weights[name].get(level, 0.0)
            for name, level in comparison_levels(x, y).items()
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
