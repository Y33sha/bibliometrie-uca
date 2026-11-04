"""Similarité de deux noms d'auteur pour l'alignement, quel que soit leur découpage entre nom de famille et prénom : « da rocha puleoto / carmella fernandes » et « fernandes da rocha / carmella puleoto »."""

from collections.abc import Callable
from functools import lru_cache
from itertools import permutations

SIMILARITY_THRESHOLD = 0.8
"""Score au-delà duquel deux noms désignent le même auteur."""

_WORD_THRESHOLD = 0.85
"""Similarité de Jaro-Winkler minimale de deux mots proches."""

_WORD_MIN_LENGTH = 5
"""Longueur minimale de deux mots comparés par Jaro-Winkler : « ali » et « alkire » restent distincts."""

_GLUED_MIN_LENGTH = 4
"""Longueur minimale d'un mot comparé à la concaténation de deux mots de l'autre nom."""


@lru_cache(maxsize=1_000_000)
def jaro_winkler(a: str, b: str) -> float:
    """Calcule la similarité de Jaro-Winkler : demi-transpositions arrondies à l'entier inférieur ; bonus de préfixe au-delà de 0,7, sur 4 caractères au plus, facteur 0,1."""
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


def _fold(word: str) -> str:
    """Rabat les transcriptions des voyelles infléchies : « ae », « oe », « ue » → « a », « o », « u »."""
    return word.replace("ae", "a").replace("oe", "o").replace("ue", "u")


def _words(name: str) -> list[str]:
    return [_fold(w) for w in name.split()]


def _merge_glued(words: list[str], other: list[str]) -> list[str]:
    """Fusionne deux mots de `words` dont la concaténation, dans un ordre ou l'autre, est un mot de `other` : « van hulse » face à « vanhulse »."""
    glued = {w for w in other if len(w) >= _GLUED_MIN_LENGTH}
    words = list(words)
    while True:
        pair = next(
            ((i, j) for i, j in permutations(range(len(words)), 2) if words[i] + words[j] in glued),
            None,
        )
        if pair is None:
            return words
        i, j = pair
        words = [w for k, w in enumerate(words) if k not in pair] + [words[i] + words[j]]


def _close_words(u: str, v: str) -> bool:
    return (
        len(u) >= _WORD_MIN_LENGTH
        and len(v) >= _WORD_MIN_LENGTH
        and jaro_winkler(u, v) >= _WORD_THRESHOLD
    )


def _word_score(x: list[str], y: list[str], *, exact_anchor: bool) -> float:
    """Renvoie la part des mots du nom le plus court retrouvés dans l'autre : mot identique, puis mot proche, puis initiale face à la première lettre d'un mot. Renvoie 0 sans mot complet commun, ou sans mot identique si `exact_anchor`."""
    a, b = _merge_glued(x, y), _merge_glued(y, x)
    if len(a) > len(b):
        a, b = b, a
    if not a:
        return 0.0
    rest_a, rest_b = list(a), list(b)

    def match(same: Callable[[str, str], bool]) -> None:
        for u in list(rest_a):
            v = next((v for v in rest_b if same(u, v)), None)
            if v is not None:
                rest_a.remove(u)
                rest_b.remove(v)

    match(lambda u, v: u == v and len(u) > 1)
    if exact_anchor and len(rest_a) == len(a):
        return 0.0
    match(_close_words)
    if len(rest_a) == len(a):
        return 0.0
    match(lambda u, v: (len(u) == 1 or len(v) == 1) and u[0] == v[0])
    return (len(a) - len(rest_a)) / len(a)


def _initials(first_name: str) -> str:
    return "".join(w[0] for w in first_name.split())


def _included_last_name(last_a: str, first_a: str, last_b: str, first_b: str) -> bool:
    """Vrai si les mots d'un nom de famille sont tous dans l'autre, et si les initiales d'un prénom commencent celles de l'autre : « porteboeuf / sarah julie » et « porteboeuf houssais / s »."""
    wa, wb = set(_words(last_a)), set(_words(last_b))
    if not wa or not wb or not (wa <= wb or wb <= wa):
        return False
    ia, ib = _initials(first_a), _initials(first_b)
    return bool(ia) and bool(ib) and (ia.startswith(ib) or ib.startswith(ia))


@lru_cache(maxsize=1_000_000)
def name_similarity(
    last_a: str, first_a: str, last_b: str, first_b: str, *, exact_anchor: bool = False
) -> tuple[float, float]:
    """Renvoie le score de deux noms, entre 0 et 1, puis la similarité de Jaro-Winkler de leurs mots triés, qui départage deux scores égaux.

    Le score vaut 1 pour un nom de famille inclus dans l'autre avec des initiales de prénom compatibles. Sinon, c'est la part des mots du nom complet le plus court retrouvés dans l'autre nom complet.

    Args:
        exact_anchor: exige un mot identique des deux côtés, en plus des mots proches.
    """
    x, y = _words(f"{last_a} {first_a}"), _words(f"{last_b} {first_b}")
    tie_break = jaro_winkler(" ".join(sorted(x)), " ".join(sorted(y)))
    if _included_last_name(last_a, first_a, last_b, first_b):
        return 1.0, tie_break
    return _word_score(x, y, exact_anchor=exact_anchor), tie_break
