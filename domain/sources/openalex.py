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

from domain.normalize import normalize_name
from domain.persons.name_matching import names_compatible, parse_raw_author_name
from domain.publication import extract_hal_id_from_url, normalize_nnt
from domain.publications.doc_types import map_doc_type

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


def parse_locations(work: dict[str, Any]) -> list[OpenalexLocation]:
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


# =============================================================
# IDs DEPUIS LES URLs
# =============================================================

# Patterns d'identifiants exposés en clair dans les URLs des locations
# OpenAlex. Volontairement co-localisés ici — OpenAlex est aujourd'hui
# le seul consommateur ; à promouvoir en module général si une autre
# source devait extraire des IDs depuis des URLs publiques par regex.
_PMID_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_PMC_URL_RE = re.compile(r"ncbi\.nlm\.nih\.gov/pmc/articles/(?:PMC)?(\d+)")


def extract_external_ids_from_urls(urls: list[str]) -> dict[str, str]:
    """Extrait les identifiants exposés dans une liste d'URLs.

    Reconnait HAL (préfixes ``hal-``/``tel-``/``halshs-``…), NNT
    (URLs ``theses.fr/<NNT>``), PMID (PubMed) et PMC. Pour chaque
    type, le **premier** match dans l'ordre des URLs gagne — l'ordre
    des URLs en entrée est donc significatif (le caller choisit
    typiquement landing_page_url avant pdf_url, primary_location avant
    autres).

    Pas de normalisation ici : le NNT n'est PAS passé par
    ``normalize_nnt`` (à l'inverse de ``extract_nnt_from_location``)
    car c'est un extracteur opportuniste depuis une URL — la
    normalisation est laissée au caller selon l'usage (les
    ``external_ids`` JSONB stockent souvent la forme brute pour
    traçabilité).
    """
    external_ids: dict[str, str] = {}
    for url in urls:
        if not external_ids.get("hal"):
            hal_id = extract_hal_id_from_url(url)
            if hal_id:
                external_ids["hal"] = hal_id
        if not external_ids.get("nnt"):
            m = _THESES_FR_URL_RE.search(url)
            if m:
                external_ids["nnt"] = m.group(1)
        if not external_ids.get("pmid"):
            m = _PMID_URL_RE.search(url)
            if m:
                external_ids["pmid"] = m.group(1)
        if not external_ids.get("pmc"):
            m = _PMC_URL_RE.search(url)
            if m:
                external_ids["pmc"] = f"PMC{m.group(1)}"
    return external_ids


def keep_orcid_if_name_matches(
    raw_full_name: str,
    oa_full_name: str,
    oa_orcid: str | None,
) -> str | None:
    """Filtre l'ORCID porté par une entité auteur OpenAlex.

    OpenAlex assigne à chaque ``authorship`` du work une entité auteur
    (``author.id`` côté OpenAlex) à laquelle est rattaché un ORCID.
    Cette assignation passe par leur propre matching nom × affiliation
    et est régulièrement fautive : un mauvais auteur attribué à la
    signature → on hérite de l'ORCID d'une autre personne.

    Garde-fou : on ne conserve l'ORCID OpenAlex que si le nom de
    l'entité auteur OpenAlex (``oa_full_name``) est compatible (au
    sens de ``names_compatible``) avec le ``raw_author_name`` que
    l'authorship porte côté source. Sinon ``None`` — l'ORCID n'est
    pas remonté en ``person_identifiers``.

    Renvoie ``oa_orcid`` si compatible, ``None`` sinon (ou si
    ``oa_orcid`` est déjà ``None``).
    """
    if not oa_orcid:
        return None
    src_ln, src_fn = parse_raw_author_name(raw_full_name)
    oa_ln, oa_fn = parse_raw_author_name(oa_full_name)
    if names_compatible(
        normalize_name(src_ln),
        normalize_name(src_fn),
        normalize_name(oa_ln),
        normalize_name(oa_fn),
    ):
        return oa_orcid
    return None


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
