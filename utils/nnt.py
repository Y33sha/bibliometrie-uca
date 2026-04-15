"""Fonctions utilitaires pour le NNT (Numéro National de Thèse).

Le NNT est un identifiant national attribué aux thèses soutenues en France.
Format typique : 2023UCFA0069 (année + code établissement + numéro séquentiel).

Il est distinct du DOI et ne doit jamais être stocké dans publications.doi.
Il est stocké dans source_publications.external_ids sous la clé "nnt".
"""

import re


def normalize_nnt(nnt: str | None) -> str | None:
    """Normalise un NNT : uppercase, strip whitespace."""
    if not nnt:
        return None
    nnt = nnt.strip().upper()
    return nnt if nnt else None


def is_theses_fr_source(work: dict) -> bool:
    """Vérifie si la primary_location d'un work OpenAlex pointe vers theses.fr."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    display_name = source.get("display_name") or ""
    if "theses.fr" in display_name.lower():
        return True
    url = location.get("landing_page_url") or ""
    if "theses.fr/" in url:
        return True
    return False


# NNT via PMH : "pmh:{NNT}" — exclut les identifiants OAI (oai:HAL:...)
_PMH_NNT_RE = re.compile(r"^pmh:([A-Za-z0-9]+)$", re.IGNORECASE)
_THESES_FR_URL_RE = re.compile(r"theses\.fr/([A-Za-z0-9]+)")


def extract_nnt_from_openalex(work: dict) -> str | None:
    """Extrait le NNT depuis un work OpenAlex dont la source est theses.fr.

    Deux méthodes :
    1. primary_location.id au format "pmh:{NNT}"
    2. landing_page_url au format "http://www.theses.fr/{NNT}/document"
    """
    location = work.get("primary_location") or {}

    # Méthode 1 : primary_location.id = "pmh:{NNT}"
    loc_id = location.get("id") or ""
    m = _PMH_NNT_RE.match(loc_id)
    if m:
        return normalize_nnt(m.group(1))

    # Méthode 2 : landing_page_url
    url = location.get("landing_page_url") or ""
    m = _THESES_FR_URL_RE.search(url)
    if m:
        return normalize_nnt(m.group(1))

    return None
