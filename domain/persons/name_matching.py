"""Découpage et comparaison des noms de personnes."""

import re
from enum import Enum

from domain.normalize import clean_raw_author_name, normalize_text

# Particules qui ouvrent un nom de famille (« da Silva », « van der Berg », « d'Incan »).
_PARTICLES = frozenset(
    {
        "abu", "ait", "al", "ben", "bin", "da", "das", "de", "del", "della", "den", "der",
        "des", "di", "do", "dos", "du", "el", "ibn", "la", "le", "les", "saint", "st", "van",
        "von",
    }
)  # fmt: skip


def _opens_family_name(word: str) -> bool:
    """Vrai si le mot est une particule, élidée comprise (« d'Incan »)."""
    return normalize_text(word) in _PARTICLES or re.match(r"d['’ʼ]", word.lower()) is not None


def is_initials(text: str) -> bool:
    """Vrai si chaque mot normalisé de `text` tient en une lettre (« M. », « O. V. », « J.-P. »)."""
    words = normalize_text(text).split()
    return bool(words) and all(len(word) == 1 for word in words)


def orient_initials(last_name: str, first_name: str) -> tuple[str, str]:
    """Renvoie (nom, prénom), inversés quand le nom se réduit à des initiales et que le prénom n'en est pas : « M. » / « Brigante » donne « Brigante » / « M. »."""
    if is_initials(last_name) and first_name.strip() and not is_initials(first_name):
        return first_name, last_name
    return last_name, first_name


def _trailing_initials_start(words: list[str]) -> int | None:
    """Renvoie l'indice du premier mot d'une suite finale d'initiales précédée d'un mot plein (« Del Buono L. » donne 2), `None` sinon."""
    if is_initials(words[0]) or not is_initials(words[-1]):
        return None
    start = len(words) - 1
    while start > 1 and is_initials(words[start - 1]):
        start -= 1
    return start


def parse_raw_author_name(raw_name: str | None) -> tuple[str, str]:
    """Découpe un nom brut en nom de famille et prénom.

    - « Nom, Prénom » : des initiales avant la virgule passent en prénom (« C., Küll »).
    - « Nom I. » : des initiales finales forment le prénom (« Del Buono L. »).
    - « Prénom Nom » : le nom de famille commence à la première particule après le premier mot (« Alison da Silva »), sinon il se réduit au dernier mot.
    """
    if not raw_name:
        return "", ""
    # Retire un identifiant entre parenthèses d'un nom brut lu sans nettoyage préalable.
    raw = clean_raw_author_name(raw_name).strip()
    if "," in raw:
        parts = raw.split(",", 1)
        return orient_initials(parts[0].strip(), parts[1].strip())
    words = raw.split()
    if len(words) < 2:
        return raw, ""
    initials = _trailing_initials_start(words)
    if initials is not None:
        return " ".join(words[:initials]), " ".join(words[initials:])
    start = next(
        (i for i in range(1, len(words) - 1) if _opens_family_name(words[i])), len(words) - 1
    )
    return " ".join(words[start:]), " ".join(words[:start])


def family_name_splits(raw_name: str | None) -> list[tuple[str, str]]:
    """Renvoie les découpages possibles d'un nom brut en nom de famille et prénom.

    Au format « Nom, Prénom » ou « Nom I. », le seul découpage de `parse_raw_author_name`. Sinon, chaque groupe de mots final après le premier mot, du plus long au plus court : « Florence Caldefie Chezet » donne (« Caldefie Chezet », « Florence ») puis (« Chezet », « Florence Caldefie »).
    """
    raw = clean_raw_author_name(raw_name or "").strip()
    if not raw:
        return []
    words = raw.split()
    if "," in raw or len(words) < 2 or _trailing_initials_start(words) is not None:
        return [parse_raw_author_name(raw)]
    return [(" ".join(words[k:]), " ".join(words[:k])) for k in range(1, len(words))]


def first_name_initials(first_name: str) -> tuple[str, ...] | None:
    """Renvoie les initiales d'un prénom réduit à des initiales, `None` pour un prénom plein ou vide.

    Un prénom est réduit quand chacun de ses mots normalisés tient en une lettre (« A. », « J.-P. »), ou quand il s'écrit en deux ou trois capitales accolées (« JP »).
    """
    words = normalize_text(first_name).split()
    if not words:
        return None
    if all(len(word) == 1 for word in words):
        return tuple(words)
    compact = re.sub(r"[\s.\-]", "", first_name)
    if 2 <= len(compact) <= 3 and compact.isalpha() and compact.isupper():
        return tuple(normalize_text(compact))
    return None


def normalize_first_name(first_name: str) -> str:
    """Normalise un prénom. Un prénom réduit à des initiales (`first_name_initials`) donne ses initiales séparées : « JP » et « J.-P. » donnent « j p »."""
    initials = first_name_initials(first_name)
    return " ".join(initials) if initials is not None else normalize_text(first_name)


def initials_extend(initials: tuple[str, ...], first_name: str) -> bool:
    """Vrai si `initials` commencent la suite des initiales de `first_name`, dans l'ordre : (« a »,) s'étend à « Abdul-Majeed », (« d »,) à « Denis M. », mais (« h »,) pas à « Bo-Hyung »."""
    own = first_name_initials(first_name) or tuple(
        word[0] for word in normalize_text(first_name).split()
    )
    return bool(initials) and own[: len(initials)] == initials


def full_first_name_extends(initials: tuple[str, ...], first_name: str) -> bool:
    """Vrai si `first_name` est un prénom plein commencé par `initials` (`initials_extend`) : (« a »,) et « Abdellah », mais ni « A. B. » ni un prénom vide."""
    return first_name_initials(first_name) is None and initials_extend(initials, first_name)


def _name_words(*parts: str) -> list[str]:
    """Renvoie les mots normalisés d'un nom, sans les chiffres, souvent une année de naissance (« Chiari, Sophie 1977- »)."""
    text = re.sub(r"\d+", " ", normalize_text(" ".join(part for part in parts if part)))
    return text.split()


def names_compatible(ln1: str, fn1: str, ln2: str, fn2: str) -> bool:
    """Vrai si deux noms désignent la même personne, à une variante de graphie près. Les noms sont bruts ou normalisés, et leur découpage en nom et prénom est indifférent.

    Chaque mot du nom le plus court s'apparie à un mot distinct de l'autre, dans n'importe quel ordre (« Combes-Motel », « Motel Combes »). Une initiale s'apparie au mot qu'elle commence (« J-L Bailly », « Jean Luc Bailly »), si une paire de mots entiers s'apparie aussi : « s pierre » et « p simon » sont distincts. Un mot peut différer d'une faute (« erick », « eric ») si le nom le plus court compte au moins deux mots.
    """
    return _words_compatible(_name_words(ln1, fn1), _name_words(ln2, fn2))


def _edit_distance(a: str, b: str) -> int:
    """Calcule la distance d'édition où insertion, suppression, substitution et échange de deux lettres voisines (« doit », « diot ») coûtent 1 (optimal string alignment)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


class _Pairing(Enum):
    """Nature de l'appariement de deux mots."""

    WORDS = "words"
    """Deux mots entiers, identiques ou à une faute près."""
    INITIAL = "initial"
    """Une initiale et un mot entier qu'elle commence."""
    INITIALS = "initials"
    """Deux initiales identiques."""


def _pairing(word: str, other: str, *, typo: bool) -> _Pairing | None:
    """Renvoie la nature de l'appariement de deux mots, `None` s'ils ne s'apparient pas. Un mot d'une lettre est une initiale. Une faute est admise seulement entre deux mots entiers, et si `typo`."""
    if len(word) == 1 or len(other) == 1:
        if word == other:
            return _Pairing.INITIALS
        if other.startswith(word) or word.startswith(other):
            return _Pairing.INITIAL
        return None
    if word == other or (typo and _edit_distance(word, other) <= 1):
        return _Pairing.WORDS
    return None


def _words_compatible(words1: list[str], words2: list[str]) -> bool:
    """Vrai si chaque mot du nom le plus court s'apparie à un mot distinct de l'autre. Une faute est admise seulement si ce nom compte au moins deux mots."""
    if not words1 or not words2:
        return False
    small, big = (words1, words2) if len(words1) <= len(words2) else (words2, words1)
    return _pair_up(small, big, typo=len(small) >= 2)


def _pair_up(
    words: list[str],
    others: list[str],
    *,
    typo: bool,
    initial: bool = False,
    whole: bool = False,
) -> bool:
    """Vrai si chaque mot de `words` s'apparie à un mot distinct de `others`, et si un appariement par initiale s'accompagne d'au moins un appariement entre deux mots entiers.

    Args:
        initial: les appariements déjà faits en comptent un par initiale.
        whole: les appariements déjà faits en comptent un entre deux mots entiers.
    """
    if not words:
        return whole or not initial
    word, rest = words[0], words[1:]
    for i, other in enumerate(others):
        pairing = _pairing(word, other, typo=typo)
        if pairing is not None and _pair_up(
            rest,
            others[:i] + others[i + 1 :],
            typo=typo,
            initial=initial or pairing is _Pairing.INITIAL,
            whole=whole or pairing is _Pairing.WORDS,
        ):
            return True
    return False
