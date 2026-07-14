"""Fonctions de comparaison et de parsing des noms de personnes.

Utilisées par le pipeline (matching cross-source dans `domain/persons/matching.py`) et par l'admin (rapprochement des doublons candidats dans les files de triage du hub personnes), qui partagent le même comparateur `names_compatible`.
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

    `normalize_name` (minuscules, sans accent ni ponctuation) puis retrait des chiffres : les années de naissance collées aux signatures de type SUDOC (« Chiari, Sophie 1977- ») parasiteraient sinon les tokens. Exception assumée à la normalisation habituelle, qui conserve [a-z0-9] pour les identifiants.
    """
    text = re.sub(r"\d+", " ", normalize_name(" ".join(part for part in parts if part)))
    return set(text.split())


def _tokens_compatible(tokens1: set[str], tokens2: set[str]) -> bool:
    """Vrai si chaque token du plus petit ensemble a un correspondant dans l'autre.

    Correspondance = token identique, ou initiale (une lettre seule préfixe d'un token de l'autre ensemble). Indépendant de l'ordre.
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

    Comparaison par ensemble de tokens : indépendante de l'ordre — gère l'inversion nom/prénom et les noms composés réordonnés (« Combes-Motel » ↔ « Motel Combes ») — et tolérante aux initiales (« J-L Bailly » ↔ « Jean Luc Bailly »). Chaque token du nom le plus court doit correspondre à un token de l'autre.

    Les entrées peuvent être brutes ou déjà normalisées (`_clean_name_tokens` normalise dans tous les cas). Le découpage nom/prénom n'a pas d'importance — les tokens sont mis en commun —, ce qui autorise à passer un nom entier en `ln` et une chaîne vide en `fn`.
    """
    return _tokens_compatible(_clean_name_tokens(ln1, fn1), _clean_name_tokens(ln2, fn2))


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


def _concat_name(part: str) -> str:
    """Fragment de nom normalisé, tokens accolés dans l'ordre (chiffres retirés)."""
    return re.sub(r"\d+", "", normalize_name(part)).replace(" ", "")


def _part_close(a: str, b: str) -> bool:
    """Deux fragments de nom (nom **ou** prénom) proches à la graphie près : même jeu de tokens (ordre indifférent), concaténation égale (« abdel mouhcine » / « abdelmouhcine », « st paul » / « stpaul »), ou distance d'édition ≤ 1 sur la concaténation (typo, translittération). Les fragments réduits à une seule lettre (initiales) sont exclus du volet distance — « b » et « x » ne sont pas proches."""
    ta, tb = _clean_name_tokens(a), _clean_name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    ca, cb = _concat_name(a), _concat_name(b)
    if ca == cb:
        return True
    return len(ca) >= 2 and len(cb) >= 2 and _edit_distance(ca, cb) <= 1


def same_person_name(ln1: str, fn1: str, ln2: str, fn2: str) -> bool:
    """Vrai si deux noms désignent la même personne, à une variation de graphie près.

    Sur-ensemble de `names_compatible` (qui gère déjà l'inversion nom/prénom et les initiales) : ajoute la tolérance aux variantes orthographiques d'une même personne — concaténation (« abdel mouhcine » / « abdelmouhcine »), particule accolée (« st paul » / « stpaul », « le roy » / « leroy »), typo ou translittération (« eric » / « erick », « toufik » / « toufic ») —, en exigeant que le nom **et** le prénom soient chacun proches. Un homonyme de patronyme au prénom franchement autre (« hervé chanal » / « hélène chanal ») ou deux initiales différentes (« b zhang » / « x zhang ») restent distincts.

    Sert de corroboration tolérante au matching par identifiant : reconnaître qu'une signature est la variante de graphie du propriétaire de l'identifiant évite de la rejeter puis d'en créer un doublon au canal nominal.
    """
    if names_compatible(ln1, fn1, ln2, fn2):
        return True
    return _part_close(ln1, ln2) and _part_close(fn1, fn2)
