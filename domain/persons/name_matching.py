"""Fonctions de comparaison et de parsing des noms de personnes.

Utilisées par le pipeline (matching cross-source dans `domain/persons/matching.py`) et par l'admin (rapprochement des doublons candidats dans les files de triage du hub personnes), qui partagent le même comparateur `names_compatible`.
"""

import re
from enum import Enum

from domain.normalize import clean_raw_author_name, normalize_name


def parse_raw_author_name(raw_name: str | None) -> tuple[str, str]:
    """Parse un raw_author_name en (last_name, first_name).

    Formats gérés :
    - "LastName, FirstName" (WoS, HAL parfois)
    - "FirstName LastName" (OpenAlex)
    """
    if not raw_name:
        return "", ""
    # Filet générique : une signature non passée par le writer (nom brut jamais assaini) ne doit pas transformer un identifiant parenthésé en nom de famille.
    raw = clean_raw_author_name(raw_name).strip()
    if "," in raw:
        parts = raw.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    words = raw.split()
    if len(words) >= 2:
        return words[-1], " ".join(words[:-1])
    return raw, ""


def _name_words(*parts: str) -> list[str]:
    """Mots normalisés d'un nom, dans l'ordre, sans les chiffres.

    `normalize_name` (minuscules, sans accent ni ponctuation) puis retrait des chiffres : les années de naissance collées aux signatures de type SUDOC (« Chiari, Sophie 1977- ») parasiteraient sinon les mots. Exception assumée à la normalisation habituelle, qui conserve [a-z0-9] pour les identifiants.
    """
    text = re.sub(r"\d+", " ", normalize_name(" ".join(part for part in parts if part)))
    return text.split()


def names_compatible(ln1: str, fn1: str, ln2: str, fn2: str) -> bool:
    """Vrai si deux noms désignent la même personne, à une variation de graphie près.

    Comparaison mot à mot, indépendante de l'ordre : chaque mot du nom le plus court doit s'apparier à un mot distinct de l'autre. Une initiale couvre donc un seul mot : « s solomon » et « sanya solodkov » restent distincts. Un appariement par initiale exige au moins un appariement entre deux mots entiers : « s pierre » et « p simon » restent distincts. Elle couvre l'inversion nom/prénom, les noms composés réordonnés (« Combes-Motel » ↔ « Motel Combes »), les initiales (« J-L Bailly » ↔ « Jean Luc Bailly »), et une faute de frappe ou de translittération par mot (« erick » ↔ « eric »). La faute n'est tolérée que si le nom le plus court compte au moins deux mots : un prénom seul, proche d'un prénom de l'autre nom, ne suffit pas. Un homonyme de patronyme au prénom franchement autre (« hervé chanal » / « hélène chanal ») ou deux initiales différentes (« b zhang » / « x zhang ») restent distincts.

    Les entrées peuvent être brutes ou déjà normalisées. Le découpage nom/prénom est indifférent, ce qui autorise à passer un nom entier en `ln` et une chaîne vide en `fn`.
    """
    return _words_compatible(_name_words(ln1, fn1), _name_words(ln2, fn2))


def _edit_distance(a: str, b: str) -> int:
    """Distance d'édition avec transposition adjacente (Damerau-Levenshtein restreinte, dite « optimal string alignment ») : insertion, suppression, substitution et échange de deux lettres voisines comptent chacun 1. La transposition couvre les coquilles fréquentes sur les noms (« doit » / « diot »)."""
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
    """Nature de l'appariement de deux mots, `None` s'ils ne s'apparient pas. Un mot d'une lettre est une initiale ; la faute n'est tolérée qu'entre deux mots entiers, et seulement si `typo`."""
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
    """Vrai si chaque mot du nom le plus court s'apparie à un mot distinct de l'autre ; la faute n'est tolérée que si ce nom compte au moins deux mots."""
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
    """Vrai si chaque mot de `words` s'apparie à un mot distinct de `others`, et si un appariement par initiale s'accompagne d'au moins un appariement entre deux mots entiers. `initial` et `whole` disent si les appariements déjà faits en contiennent un."""
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
