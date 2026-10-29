"""Lecture des enregistrements sources OpenAlex par la normalisation : conventions des champs d'OpenAlex.

Les payloads reçus de l'API sont décrits par `JsonValue` : leur forme est celle qu'ils ont, et chaque champ lu passe par un accesseur qui la contrôle.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from domain.publications.identifiers import (
    extract_doi_from_url,
    extract_hal_id_from_url,
    is_hal_host,
    normalize_arxiv_id,
    normalize_nnt,
    normalize_pmcid,
    normalize_pmid,
)
from domain.publications.metadata import OaStatus
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.types import JsonValue, as_mapping, as_str
from domain.urls import is_host, url_host

# OpenAlex donne ses identifiants en URL (`https://openalex.org/<id>`) pour tous les types d'entité : W works, A auteurs, S sources, I institutions, P éditeurs. La base garde la forme courte (`S20400310`).
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


BULK_AUTHORSHIPS_CAP = 100
"""Nombre maximal d'auteurs d'un work dans une réponse bulk d'OpenAlex. Un work qui en compte autant est peut-être tronqué ; sa requête individuelle renvoie tous ses auteurs."""


def authors_may_be_truncated(work: Mapping[str, JsonValue]) -> bool:
    """Vrai quand un work reçu d'une réponse de liste d'OpenAlex (`/works?filter=…`) compte autant d'auteurs que le plafond : sa liste est peut-être tronquée."""
    authorships = work.get("authorships")
    return isinstance(authorships, list) and len(authorships) == BULK_AUTHORSHIPS_CAP


@dataclass(frozen=True, slots=True)
class OpenalexLocation:
    """Une `location` d'un work OpenAlex, principale ou non.

    OpenAlex donne la localisation principale (`primary_location`) et toutes les localisations du work (`locations`), en général la principale en tête. Tous les champs peuvent manquer : OpenAlex renvoie des localisations partielles (sans page, source non identifiée…).
    """

    location_id: str | None  # location.id (ex. "pmh:2023UCFAC123")
    landing_page_url: str | None  # location.landing_page_url
    source_id: str | None  # location.source.id (URL OpenAlex)
    source_type: str | None  # 'journal' | 'repository' | 'ebook platform' | …
    source_display_name: str | None  # ex. 'HAL Archive ouverte', 'theses.fr'
    source_homepage_url: str | None  # ex. la page d'accueil de HAL


def _parse_one_location(loc: JsonValue) -> OpenalexLocation | None:
    loc_fields = as_mapping(loc)
    if not loc_fields:
        return None
    src = as_mapping(loc_fields.get("source"))
    return OpenalexLocation(
        location_id=as_str(loc_fields.get("id")),
        landing_page_url=as_str(loc_fields.get("landing_page_url")),
        source_id=as_str(src.get("id")),
        source_type=as_str(src.get("type")),
        source_display_name=as_str(src.get("display_name")),
        source_homepage_url=as_str(src.get("homepage_url")),
    )


def parse_primary_location(work: Mapping[str, JsonValue]) -> OpenalexLocation | None:
    """Vue structurée de `work.primary_location`. None si absent."""
    return _parse_one_location(work.get("primary_location"))


def is_theses_fr_location(loc: OpenalexLocation) -> bool:
    """Vrai si la localisation désigne theses.fr, par son nom ou son URL."""
    if "theses.fr" in (loc.source_display_name or "").lower():
        return True
    return is_host(loc.landing_page_url, "theses.fr")


def is_repository_location(loc: OpenalexLocation) -> bool:
    """Vrai si la source de la localisation est un `repository` (HAL, Zenodo…)."""
    return loc.source_type == "repository"


def is_hal_location(loc: OpenalexLocation) -> bool:
    """Vrai si la localisation désigne HAL : sa page est un identifiant HAL reconnu (`extract_hal_id_from_url`), ou sa source est un `repository` dont la page d'accueil est un portail HAL ou dont le nom contient « hal »."""
    if extract_hal_id_from_url(loc.landing_page_url) is not None:
        return True
    if loc.source_type == "repository":
        host = url_host(loc.source_homepage_url)
        if host and is_hal_host(host):
            return True
        if "hal" in (loc.source_display_name or "").lower():
            return True
    return False


def names_publisher(loc: OpenalexLocation | None) -> bool:
    """Vrai si la source de la localisation principale nomme l'éditeur du work. HAL, theses.fr et les autres entrepôts (Zenodo, SPIRE…) hébergent le work sans le publier. Sans localisation principale, la source est réputée nommer l'éditeur."""
    if loc is None:
        return True
    return not (is_hal_location(loc) or is_theses_fr_location(loc) or is_repository_location(loc))


def names_serial(loc: OpenalexLocation | None) -> bool:
    """Vrai si la source de la localisation principale est la revue ou la collection du work. Une plateforme d'ebooks a l'éditeur pour organisation hôte, et ne contient aucun document."""
    return names_publisher(loc) and (loc is None or loc.source_type != "ebook platform")


# NNT d'un identifiant PMH : « pmh:{NNT} », hors identifiants OAI (`oai:HAL:…`).
_PMH_NNT_RE = re.compile(r"^pmh:([A-Za-z0-9]+)$", re.IGNORECASE)
_THESES_FR_URL_RE = re.compile(r"theses\.fr/([A-Za-z0-9]+)")


def extract_nnt_from_location(loc: OpenalexLocation) -> str | None:
    """NNT d'une localisation theses.fr : d'après `location.id` (`pmh:{NNT}`), à défaut sa page (`…/theses.fr/{NNT}/…`)."""
    if loc.location_id:
        m = _PMH_NNT_RE.match(loc.location_id)
        if m:
            return normalize_nnt(m.group(1))
    if loc.landing_page_url:
        m = _THESES_FR_URL_RE.search(loc.landing_page_url)
        if m:
            return normalize_nnt(m.group(1))
    return None


# Statuts open access qu'OpenAlex expose (`open_access.oa_status`), reconnus par `map_openalex_oa_status`.
_KNOWN_OA_STATUSES = frozenset(
    {
        OaStatus.GOLD,
        OaStatus.DIAMOND,
        OaStatus.HYBRID,
        OaStatus.BRONZE,
        OaStatus.GREEN,
        OaStatus.CLOSED,
    }
)


def map_openalex_oa_status(raw: str | None) -> str | None:
    """Statut open access (`OaStatus`) d'un `open_access.oa_status` d'OpenAlex.

    OpenAlex emploie les mêmes valeurs que `OaStatus` (gold, diamond, hybrid, bronze, green, closed). Une valeur vide donne `None` : les autres sources en décident (`best_oa_status`), et un champ vide reste distinct de `closed`. Une valeur inattendue donne `unknown`.
    """
    if not raw:
        return None
    if raw in _KNOWN_OA_STATUSES:
        return raw
    return "unknown"


def url_identifiers(urls: list[str]) -> list[SourceIdentifier]:
    """Identifiants secondaires exposés dans une liste d'URLs, dans leur ordre : `hal_id` (préfixes `hal-`/`tel-`/`halshs-`…), NNT (URLs `theses.fr/<NNT>`), PMID (PubMed), PMCID et arXiv."""
    identifiers: list[SourceIdentifier] = []
    for url in urls:
        for id_type, value in (
            (SourceIdentifierType.HAL_ID, extract_hal_id_from_url(url)),
            (
                SourceIdentifierType.NNT,
                m.group(1) if (m := _THESES_FR_URL_RE.search(url)) else None,
            ),
            (SourceIdentifierType.PMID, normalize_pmid(url)),
            (SourceIdentifierType.PMCID, normalize_pmcid(url)),
            (SourceIdentifierType.ARXIV_ID, normalize_arxiv_id(url)),
        ):
            if value:
                identifiers.append(SourceIdentifier(id_type, value, SourceIdentifierRole.SECONDARY))
    return identifiers


def openalex_derived_identifier(primary: OpenalexLocation | None) -> SourceIdentifier | None:
    """Identifiant de la localisation principale d'un work : NNT d'une localisation theses.fr, sinon premier `hal_id`, DOI, PMCID, PMID ou identifiant arXiv de sa page ou de son identifiant de localisation."""
    if primary is None:
        return None
    if is_theses_fr_location(primary) and (nnt := extract_nnt_from_location(primary)):
        return SourceIdentifier(SourceIdentifierType.NNT, nnt, SourceIdentifierRole.DERIVED)
    for id_type, extract in (
        (SourceIdentifierType.HAL_ID, extract_hal_id_from_url),
        (SourceIdentifierType.DOI, extract_doi_from_url),
        (SourceIdentifierType.PMCID, normalize_pmcid),
        (SourceIdentifierType.PMID, normalize_pmid),
        (SourceIdentifierType.ARXIV_ID, normalize_arxiv_id),
    ):
        for raw in (primary.landing_page_url, primary.location_id):
            if value := extract(raw):
                return SourceIdentifier(id_type, value, SourceIdentifierRole.DERIVED)
    return None
