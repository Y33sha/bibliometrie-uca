"""Règles métier pures spécifiques à la source OpenAlex.

Interprétation des champs propres au schéma OpenAlex — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique OpenAlex
pour le reste du pipeline.
"""

import re
from dataclasses import dataclass

from domain.doc_types import map_doc_type
from domain.publication import normalize_nnt

# =============================================================
# LOCATIONS
# =============================================================


@dataclass(frozen=True, slots=True)
class OpenalexLocation:
    """Vue structurée d'une `location` d'un work OpenAlex.

    OpenAlex expose deux entrées de même shape :
    - `work.primary_location` : la location principale (où OA a
      moissonné le document).
    - `work.locations` (liste) : toutes les locations connues pour le
      document (incluant typiquement la primary en `locations[0]`).

    Cette dataclass représente une location quelconque, indépendamment
    de son rôle primary/secondaire — le caller distingue via les
    parsers `parse_primary_location` (singulier) vs `parse_locations`
    (toutes).

    Tous les champs sont nullable car OpenAlex peut retourner une
    location partielle (publi sans landing page, source non
    identifiée…).
    """

    location_id: str | None  # location.id (ex. "pmh:2023UCFAC123")
    landing_page_url: str | None  # location.landing_page_url
    source_id: str | None  # location.source.id (URL OpenAlex)
    source_type: str | None  # 'journal' | 'repository' | 'ebook platform' | …
    source_display_name: str | None  # ex. 'HAL Archive ouverte', 'theses.fr'
    source_homepage_url: str | None  # ex. 'https://hal.science'


def _parse_one_location(loc: dict | None) -> OpenalexLocation | None:
    if not loc:
        return None
    src = loc.get("source") or {}
    return OpenalexLocation(
        location_id=loc.get("id"),
        landing_page_url=loc.get("landing_page_url"),
        source_id=src.get("id"),
        source_type=src.get("type"),
        source_display_name=src.get("display_name"),
        source_homepage_url=src.get("homepage_url"),
    )


def parse_primary_location(work: dict) -> OpenalexLocation | None:
    """Vue structurée de `work.primary_location`. None si absent."""
    return _parse_one_location(work.get("primary_location"))


def parse_locations(work: dict) -> list[OpenalexLocation]:
    """Vue structurée de toutes les `work.locations`. Inclut la primary."""
    return [
        parsed
        for loc in (work.get("locations") or [])
        if (parsed := _parse_one_location(loc)) is not None
    ]


# =============================================================
# PRÉDICATS SUR LES LOCATIONS
# =============================================================


def is_theses_fr_location(loc: OpenalexLocation) -> bool:
    """True si la location pointe vers theses.fr (display_name ou URL)."""
    if "theses.fr" in (loc.source_display_name or "").lower():
        return True
    return "theses.fr/" in (loc.landing_page_url or "")


def is_repository_location(loc: OpenalexLocation) -> bool:
    """True si la location est de type 'repository' (HAL, Zenodo, etc.)."""
    return loc.source_type == "repository"


# Préfixes HAL dans les URL des landing pages : hal-, tel-, halshs-, etc.
_HAL_LANDING_RE = re.compile(r"/(?:hal|tel|halshs|inserm|pasteur|cea|ineris)-\d+")


def is_hal_location(loc: OpenalexLocation) -> bool:
    """True si la location pointe vers HAL.

    Trois signaux :
    1. URL de la landing page contient un préfixe HAL identifié.
    2. `source.type == 'repository'` ET `source.homepage_url` contient 'hal'.
    3. `source.type == 'repository'` ET `source.display_name` contient 'hal'.
    """
    if loc.landing_page_url and _HAL_LANDING_RE.search(loc.landing_page_url):
        return True
    if loc.source_type == "repository":
        if "hal" in (loc.source_homepage_url or "").lower():
            return True
        if "hal" in (loc.source_display_name or "").lower():
            return True
    return False


def should_skip_publisher_journal(loc: OpenalexLocation | None) -> bool:
    """True si la primary_location ne représente pas un éditeur — donc
    on ne cherche ni publisher ni journal pour ce work.

    Couvre HAL, theses.fr et tout autre repository (Zenodo, SPIRE, etc.).
    `None` (pas de primary) → False par défaut (rare en pratique).
    """
    if loc is None:
        return False
    return is_hal_location(loc) or is_theses_fr_location(loc) or is_repository_location(loc)


# =============================================================
# EXTRACTEURS
# =============================================================


# NNT via PMH : "pmh:{NNT}" — exclut les identifiants OAI (oai:HAL:...)
_PMH_NNT_RE = re.compile(r"^pmh:([A-Za-z0-9]+)$", re.IGNORECASE)
_THESES_FR_URL_RE = re.compile(r"theses\.fr/([A-Za-z0-9]+)")


def extract_nnt_from_location(loc: OpenalexLocation) -> str | None:
    """Extrait le NNT d'une location quand celle-ci pointe vers theses.fr.

    Cascade :
    1. `location.id` au format `"pmh:{NNT}"` (OAI-PMH harvest)
    2. `landing_page_url` au format `"…/theses.fr/{NNT}/…"`
    """
    if loc.location_id:
        m = _PMH_NNT_RE.match(loc.location_id)
        if m:
            return normalize_nnt(m.group(1))
    if loc.landing_page_url:
        m = _THESES_FR_URL_RE.search(loc.landing_page_url)
        if m:
            return normalize_nnt(m.group(1))
    return None


# Statuts OA exposés par OpenAlex (`open_access.oa_status`). OpenAlex
# utilise les mêmes labels que notre enum canonique, plus `diamond`
# qu'ils ont commencé à exposer en 2023. Le set est utilisé pour
# valider/dispatcher dans `map_openalex_oa_status`.
_KNOWN_OA_STATUSES = frozenset({"gold", "diamond", "hybrid", "bronze", "green", "closed"})


def map_openalex_oa_status(raw: str | None) -> str | None:
    """Mapping OpenAlex `open_access.oa_status` → enum oa_status canonique.

    OpenAlex utilise les mêmes labels que notre enum (gold, diamond,
    hybrid, bronze, green, closed). Mapping identitaire pour les
    valeurs connues, plus :

    - `None` ou `""` → `None` (OpenAlex ne s'est pas prononcé ; on
      délègue aux autres sources via `best_oa_status` côté
      `refresh_from_sources`. Cas rare : OpenAlex peuple presque
      toujours `open_access.oa_status` quand `open_access` est
      présent. Cohérent avec la sémantique HAL/ScanR : on ne mappe
      pas un champ vide à `closed`.)
    - valeur inattendue → `'unknown'` (catch-all si OpenAlex introduit
      un nouveau label qu'on n'a pas encore intégré au mapping).
    """
    if not raw:
        return None
    if raw in _KNOWN_OA_STATUSES:
        return raw
    return "unknown"


def correct_openalex_doc_type(
    raw_type: str | None,
    *,
    is_theses_fr: bool,
    landing_page_url: str | None,
) -> str:
    """Détermine le doc_type canonique d'une publication associée à un
    work OpenAlex, en corrigeant les imprécisions OpenAlex à partir de
    signaux source-spécifiques.

    OpenAlex classe parfois de manière imprécise les ressources hébergées
    par certaines sources canoniques (theses.fr, dumas, …). Cette fonction
    applique les overrides connus avant de retomber sur le mapping
    OpenAlex standard.

    Cascade :
      1. is_theses_fr → 'thesis' (theses.fr fait autorité sur les thèses
         françaises, peu importe la classification OpenAlex)
      2. raw_type=='dissertation' + URL en `dumas.*` → 'memoir'
         (DUMAS héberge des mémoires de master, classés à tort en
         'dissertation' par OpenAlex)
      3. sinon → `map_doc_type(raw_type, 'openalex')` (mapping standard)

    À noter : cette fonction sert à la **création/lookup de la table
    canonique `publications`**. La colonne `source_publications.doc_type`
    stocke quant à elle le raw OpenAlex sans correction, par convention
    (`work.get("type")` lu directement dans `insert_openalex_document`).

    À étendre avec le chantier suppléments : ajouter signaux DOI/title
    pour reclasser les figshare/Zenodo « Additional file… » en `'other'`.

    Note d'architecture : ces règles sont **conceptuellement
    source-agnostiques** (« theses.fr fait toujours autorité sur les
    thèses », « dumas → mémoire », « Zenodo supplément → other »).
    En pratique seul OpenAlex provoque ces erreurs de doc_type
    aujourd'hui (parce qu'il moissonne ces sources sans en respecter
    la nomenclature), donc on garde la fonction ici. Si un jour une
    autre source produit le même type d'imprécisions, on pourra
    promouvoir la fonction (ou ses helpers) dans `domain/doc_types.py`.
    """
    if is_theses_fr:
        return "thesis"
    if (raw_type or "").lower() == "dissertation":
        if landing_page_url and "dumas." in landing_page_url:
            return "memoir"
    return map_doc_type(raw_type, "openalex")
