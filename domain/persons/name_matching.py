"""Fonctions de comparaison et de parsing des noms de personnes.

Utilisées par le pipeline (matching cross-source dans `domain/persons/matching.py`) et par l'admin (rapprochement des doublons candidats dans les files de triage du hub personnes), qui partagent le même comparateur `names_compatible`.
"""

import re

from domain.normalize import clean_raw_author_name, normalize_name

# Nombre maximal de mots consécutifs qu'une graphie accole (« de la fontaine » / « delafontaine »).
_MAX_JOINED_WORDS = 3
# Longueur minimale de deux mots comparés à une faute près : les initiales en sont exclues, « b » et « x » restent distincts.
_TYPO_MIN_LENGTH = 2


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

    Comparaison mot à mot, indépendante de l'ordre : chaque mot du nom le plus court doit trouver un correspondant dans l'autre. Elle couvre l'inversion nom/prénom, les noms composés réordonnés (« Combes-Motel » ↔ « Motel Combes »), les initiales (« J-L Bailly » ↔ « Jean Luc Bailly »), une faute de frappe ou de translittération par mot (« erick » ↔ « eric »), et les mots accolés (« le roy » ↔ « leroy »). La faute n'est tolérée que si le nom le plus court compte au moins deux mots : un prénom seul, proche d'un prénom de l'autre nom, ne suffit pas. Un homonyme de patronyme au prénom franchement autre (« hervé chanal » / « hélène chanal ») ou deux initiales différentes (« b zhang » / « x zhang ») restent distincts.

    Les entrées peuvent être brutes ou déjà normalisées. Le découpage nom/prénom est indifférent, ce qui autorise à passer un nom entier en `ln` et une chaîne vide en `fn`.
    """
    variants1 = _joined_variants(_name_words(ln1, fn1))
    variants2 = _joined_variants(_name_words(ln2, fn2))
    return any(_words_compatible(v1, v2) for v1 in variants1 for v2 in variants2)


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


def _joined_variants(words: list[str]) -> list[list[str]]:
    """La suite de mots d'un nom, puis chaque variante où une série de mots consécutifs est accolée en un seul."""
    variants = [words]
    for size in range(2, _MAX_JOINED_WORDS + 1):
        for start in range(len(words) - size + 1):
            joined = "".join(words[start : start + size])
            variants.append([*words[:start], joined, *words[start + size :]])
    return variants


def _words_match(word: str, other: str, *, typo: bool) -> bool:
    """Mot identique, initiale de l'autre, ou, si `typo`, à une faute près."""
    if word == other:
        return True
    if (len(word) == 1 and other.startswith(word)) or (len(other) == 1 and word.startswith(other)):
        return True
    return (
        typo and min(len(word), len(other)) >= _TYPO_MIN_LENGTH and _edit_distance(word, other) <= 1
    )


def _words_compatible(words1: list[str], words2: list[str]) -> bool:
    """Vrai si chaque mot du nom le plus court trouve un correspondant dans l'autre ; la faute n'est tolérée que si ce nom compte au moins deux mots."""
    if not words1 or not words2:
        return False
    small, big = (words1, words2) if len(words1) <= len(words2) else (words2, words1)
    typo = len(small) >= 2
    return all(any(_words_match(word, other, typo=typo) for other in big) for word in small)
