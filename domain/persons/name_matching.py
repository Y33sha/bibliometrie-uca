"""Fonctions de comparaison et de parsing des noms de personnes.

Utilisées par le pipeline (matching cross-source dans
`domain/persons/matching.py`) et par l'admin (rapprochement des doublons candidats
dans les files de triage du hub personnes), qui partagent le même comparateur
`names_compatible`.
"""

import re

from domain.normalize import normalize_name


def parse_raw_author_name(raw_name: str | None) -> tuple[str, str]:
    """Parse un raw_author_name en (last_name, first_name).

    Formats gérés :
    - "LastName, FirstName" (WoS, HAL parfois)
    - "FirstName LastName" (OpenAlex)
    """
    if not raw_name:
        return "", ""
    raw = raw_name.strip()
    if "," in raw:
        parts = raw.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    words = raw.split()
    if len(words) >= 2:
        return words[-1], " ".join(words[:-1])
    return raw, ""


def _clean_name_tokens(*parts: str) -> set[str]:
    """Ensemble de tokens normalisés d'un nom, sans les chiffres.

    `normalize_name` (minuscules, sans accent ni ponctuation) puis retrait des
    chiffres : les années de naissance collées aux signatures de type SUDOC
    (« Chiari, Sophie 1977- ») parasiteraient sinon les tokens. Exception assumée à
    la normalisation habituelle, qui conserve [a-z0-9] pour les identifiants.
    """
    text = re.sub(r"\d+", " ", normalize_name(" ".join(part for part in parts if part)))
    return set(text.split())


def _tokens_compatible(tokens1: set[str], tokens2: set[str]) -> bool:
    """Vrai si chaque token du plus petit ensemble a un correspondant dans l'autre.

    Correspondance = token identique, ou initiale (une lettre seule préfixe d'un
    token de l'autre ensemble). Indépendant de l'ordre.
    """
    if not tokens1 or not tokens2:
        return False
    small, big = (tokens1, tokens2) if len(tokens1) <= len(tokens2) else (tokens2, tokens1)
    for token in small:
        if token in big:
            continue
        if len(token) == 1 and any(other.startswith(token) for other in big):
            continue
        if any(len(other) == 1 and token.startswith(other) for other in big):
            continue
        return False
    return True


def names_compatible(ln1: str, fn1: str, ln2: str, fn2: str) -> bool:
    """Vrai si deux noms (nom, prénom) désignent vraisemblablement la même personne.

    Comparaison par ensemble de tokens : indépendante de l'ordre — gère l'inversion
    nom/prénom et les noms composés réordonnés (« Combes-Motel » ↔ « Motel Combes »)
    — et tolérante aux initiales (« J-L Bailly » ↔ « Jean Luc Bailly »). Chaque token
    du nom le plus court doit correspondre à un token de l'autre.

    Les entrées peuvent être brutes ou déjà normalisées (`_clean_name_tokens`
    normalise dans tous les cas). Le découpage nom/prénom n'a pas d'importance — les
    tokens sont mis en commun —, ce qui autorise à passer un nom entier en `ln` et
    une chaîne vide en `fn`.
    """
    return _tokens_compatible(_clean_name_tokens(ln1, fn1), _clean_name_tokens(ln2, fn2))
