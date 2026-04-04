"""Fonctions de compatibilité de noms pour la déduplication de personnes.

Utilisées par :
- create_persons_from_source_authorships.py (pipeline)
- admin_person_duplicates (backend)
"""

from utils.normalize import normalize_name


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


def first_names_compatible(fn1: str, fn2: str) -> bool:
    """Vérifie si deux prénoms normalisés sont compatibles.

    Compatible = identique, initiale de l'autre, ou préfixe (Jean vs Jean-Luc).
    """
    if not fn1 or not fn2:
        return False
    if fn1[0] != fn2[0]:
        return False
    if fn1 == fn2:
        return True
    # Initiale
    if len(fn1) == 1 or len(fn2) == 1:
        return True
    # Préfixe (avec espace: "jean" vs "jean luc")
    fn1s = fn1.replace("-", " ")
    fn2s = fn2.replace("-", " ")
    if fn1s.startswith(fn2s + " ") or fn2s.startswith(fn1s + " "):
        return True
    return False


def last_names_compatible(ln1: str, ln2: str) -> bool:
    """Vérifie si deux noms de famille normalisés sont compatibles.

    Compatible = identique, ou l'un est préfixe de l'autre (composé vs simple).
    """
    if not ln1 or not ln2:
        return False
    if ln1 == ln2:
        return True
    ln1s = ln1.replace("-", " ")
    ln2s = ln2.replace("-", " ")
    if ln1s == ln2s:
        return True
    if ln2s.startswith(ln1s + " ") or ln1s.startswith(ln2s + " "):
        return True
    return False


def names_compatible(ln1: str, fn1: str, ln2: str, fn2: str) -> bool:
    """Vérifie si deux paires (nom, prénom) normalisées sont compatibles.

    Gère aussi l'inversion nom/prénom.
    """
    # Ordre normal
    if last_names_compatible(ln1, ln2) and first_names_compatible(fn1, fn2):
        return True
    # Inversion nom/prénom
    if last_names_compatible(ln1, fn2) and first_names_compatible(fn1, ln2):
        return True
    return False
