"""Règles métier pures spécifiques à la source OpenAlex.

Interprétation des champs propres au schéma OpenAlex — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique OpenAlex
pour le reste du pipeline.

Les `dict[str, Any]` ici sont des payloads JSON bruts de l'API OpenAlex
(frontière dynamique avec une source externe, schéma non typé).
"""

import re
from dataclasses import dataclass
from typing import Any

from domain.publications.identifiers import (
    extract_hal_id_from_url,
    normalize_arxiv_id,
    normalize_nnt,
    normalize_pmcid,
    normalize_pmid,
)

# =============================================================
# IDENTIFIANT OPENALEX (court ↔ URL)
# =============================================================

# OpenAlex expose ses identifiants sous forme d'URL (`https://openalex.org/<id>`)
# pour tous les types d'entité : W works, A auteurs, S sources, I institutions,
# P éditeurs. En base on conserve la forme courte (`S20400310`).
_OPENALEX_ID_PREFIX = "https://openalex.org/"


def short_openalex_id(id_or_url: str) -> str:
    """Forme courte d'un identifiant OpenAlex (`https://openalex.org/S20400310` → `S20400310`).

    Inchangé si l'entrée est déjà courte.
    """
    if id_or_url.startswith(_OPENALEX_ID_PREFIX):
        return id_or_url[len(_OPENALEX_ID_PREFIX) :]
    return id_or_url


def full_openalex_id(id_or_url: str) -> str:
    """Forme URL d'un identifiant OpenAlex (`S20400310` → `https://openalex.org/S20400310`).

    Inchangé si l'entrée est déjà une URL.
    """
    if id_or_url.startswith("http"):
        return id_or_url
    return _OPENALEX_ID_PREFIX + id_or_url


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
    de son rôle primary/secondaire ; `parse_primary_location` en
    construit la vue depuis `work.primary_location`.

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


def _parse_one_location(loc: dict[str, Any] | None) -> OpenalexLocation | None:
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


def parse_primary_location(work: dict[str, Any]) -> OpenalexLocation | None:
    """Vue structurée de `work.primary_location`. None si absent."""
    return _parse_one_location(work.get("primary_location"))


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


# =============================================================
# IDs DEPUIS LES URLs
# =============================================================


def extract_external_ids_from_urls(urls: list[str]) -> dict[str, str | list[str]]:
    """Extrait les identifiants exposés dans une liste d'URLs.

    Reconnait HAL (préfixes `hal-`/`tel-`/`halshs-`…), NNT
    (URLs `theses.fr/<NNT>`), PMID (PubMed), PMCID et arXiv.

    `hal_id` est **multivalué** : une œuvre peut référencer plusieurs
    dépôts HAL (chapitres, versions, doublons), tous collectés (liste
    dédupliquée, ordre d'apparition). Les autres clés sont 1:1 avec un
    document → premier match gagnant (l'ordre des URLs est significatif :
    le caller choisit typiquement landing_page_url avant pdf_url).

    Les extracteurs d'ID par URL (PMID/PMCID/arXiv/HAL) vivent dans
    `domain.publications.identifiers` (neutres, réutilisés par HAL).

    Pas de normalisation du NNT ici (à l'inverse de
    `extract_nnt_from_location`) — extracteur opportuniste depuis une
    URL, la normalisation est laissée au caller.
    """
    external_ids: dict[str, str | list[str]] = {}
    hal_ids: list[str] = []
    for url in urls:
        if (hal_id := extract_hal_id_from_url(url)) and hal_id not in hal_ids:
            hal_ids.append(hal_id)
        if "nnt" not in external_ids:
            m = _THESES_FR_URL_RE.search(url)
            if m:
                external_ids["nnt"] = m.group(1)
        if "pmid" not in external_ids:
            if pmid := normalize_pmid(url):
                external_ids["pmid"] = pmid
        if "pmcid" not in external_ids:
            if pmcid := normalize_pmcid(url):
                external_ids["pmcid"] = pmcid
        if "arxiv_id" not in external_ids:
            if arxiv_id := normalize_arxiv_id(url):
                external_ids["arxiv_id"] = arxiv_id
    if hal_ids:
        external_ids["hal_id"] = hal_ids
    return external_ids
