"""Lecture des payloads OpenAlex par la normalisation : conventions des champs d'OpenAlex.

Les payloads reçus de l'API sont typés `JsonValue`. Chaque champ lu passe par un accesseur qui contrôle sa forme.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from domain.documents.identifiers import (
    NNT,
    PMID,
    CdsId,
    HALId,
    arxiv_doi,
    extract_doi_from_url,
    is_hal_host,
)
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.types import JsonValue, as_mapping, as_str
from domain.urls import is_host, is_link_header_fragment, url_host

_OPENALEX_ID_PREFIX = "https://openalex.org/"
"""OpenAlex donne ses identifiants en URL (`https://openalex.org/<id>`) pour tous les types d'entité : W works, A auteurs, S sources, I institutions, P éditeurs. La base garde la forme courte (`S20400310`)."""


def short_openalex_id(id_or_url: str) -> str:
    """Renvoie la forme courte d'un identifiant OpenAlex (`https://openalex.org/S20400310` → `S20400310`).

    Inchangé si l'entrée est déjà courte.
    """
    if id_or_url.startswith(_OPENALEX_ID_PREFIX):
        return id_or_url[len(_OPENALEX_ID_PREFIX) :]
    return id_or_url


def full_openalex_id(id_or_url: str) -> str:
    """Renvoie la forme URL d'un identifiant OpenAlex (`S20400310` → `https://openalex.org/S20400310`).

    Inchangé si l'entrée est déjà une URL.
    """
    if id_or_url.startswith("http"):
        return id_or_url
    return _OPENALEX_ID_PREFIX + id_or_url


BULK_AUTHORSHIPS_CAP = 100
"""Nombre maximal d'auteurs d'un work dans une réponse bulk d'OpenAlex. Un work au plafond est peut-être tronqué ; sa requête individuelle renvoie tous ses auteurs."""


def authors_may_be_truncated(work: Mapping[str, JsonValue]) -> bool:
    """Renvoie vrai quand un work reçu d'une réponse de liste d'OpenAlex (`/works?filter=…`) atteint le plafond d'auteurs : sa liste est peut-être tronquée."""
    authorships = work.get("authorships")
    return isinstance(authorships, list) and len(authorships) == BULK_AUTHORSHIPS_CAP


@dataclass(frozen=True, slots=True)
class OpenalexLocation:
    """Une `location` d'un work OpenAlex, principale ou non.

    OpenAlex donne la localisation principale (`primary_location`) et toutes les localisations du work (`locations`), en général la principale en tête. Tous les champs peuvent manquer : OpenAlex renvoie des localisations partielles (sans page, source non identifiée…).
    """

    location_id: str | None
    """`location.id` (ex. `pmh:2023UCFAC123`)."""
    landing_page_url: str | None
    """`location.landing_page_url`."""
    source_id: str | None
    """`location.source.id` (URL OpenAlex)."""
    source_type: str | None
    """`journal`, `repository`, `ebook platform`…"""
    source_display_name: str | None
    """Ex. `HAL Archive ouverte`, `theses.fr`."""
    source_homepage_url: str | None
    """Ex. la page d'accueil de HAL."""


def location_url(loc: Mapping[str, JsonValue], key: str) -> str | None:
    """Renvoie l'adresse `key` d'une localisation (`landing_page_url`, `pdf_url`). OpenAlex recopie parfois une adresse d'en-tête HTTP `Link` (`is_link_header_fragment`) : elle est écartée."""
    url = as_str(loc.get(key))
    return None if url is None or is_link_header_fragment(url) else url


def _parse_one_location(loc: JsonValue) -> OpenalexLocation | None:
    loc_fields = as_mapping(loc)
    if not loc_fields:
        return None
    src = as_mapping(loc_fields.get("source"))
    return OpenalexLocation(
        location_id=as_str(loc_fields.get("id")),
        landing_page_url=location_url(loc_fields, "landing_page_url"),
        source_id=as_str(src.get("id")),
        source_type=as_str(src.get("type")),
        source_display_name=as_str(src.get("display_name")),
        source_homepage_url=as_str(src.get("homepage_url")),
    )


def parse_primary_location(work: Mapping[str, JsonValue]) -> OpenalexLocation | None:
    """Renvoie la vue structurée de `work.primary_location`, ou `None` en son absence."""
    return _parse_one_location(work.get("primary_location"))


def is_theses_fr_location(loc: OpenalexLocation) -> bool:
    """Renvoie vrai si la localisation désigne theses.fr, par son nom ou son URL."""
    if "theses.fr" in (loc.source_display_name or "").lower():
        return True
    return is_host(loc.landing_page_url, "theses.fr")


def is_repository_location(loc: OpenalexLocation) -> bool:
    """Renvoie vrai si la source de la localisation est un `repository` (HAL, Zenodo…)."""
    return loc.source_type == "repository"


def is_hal_location(loc: OpenalexLocation) -> bool:
    """Renvoie vrai si la localisation désigne HAL : sa page est un identifiant HAL reconnu (`HALId.normalize`), ou sa source est un `repository` à page d'accueil sur un portail HAL ou à nom contenant « hal »."""
    if HALId.normalize(loc.landing_page_url) is not None:
        return True
    if loc.source_type == "repository":
        host = url_host(loc.source_homepage_url)
        if host and is_hal_host(host):
            return True
        if "hal" in (loc.source_display_name or "").lower():
            return True
    return False


def names_publisher(loc: OpenalexLocation | None) -> bool:
    """Renvoie vrai si la source de la localisation principale nomme l'éditeur du work.

    HAL, theses.fr et les autres entrepôts (Zenodo, SPIRE…) hébergent le work sans le publier. Sans localisation principale, la source est réputée nommer l'éditeur.
    """
    if loc is None:
        return True
    return not (is_hal_location(loc) or is_theses_fr_location(loc) or is_repository_location(loc))


def names_serial(loc: OpenalexLocation | None) -> bool:
    """Renvoie vrai si la source de la localisation principale est la revue ou la collection du work.

    Une plateforme d'ebooks a l'éditeur pour organisation hôte, et ne contient aucun document.
    """
    return names_publisher(loc) and (loc is None or loc.source_type != "ebook platform")


_PMH_NNT_RE = re.compile(r"^pmh:([A-Za-z0-9]+)$", re.IGNORECASE)
"""NNT d'un identifiant PMH : « pmh:{NNT} », hors identifiants OAI (`oai:HAL:…`)."""
_THESES_FR_URL_RE = re.compile(r"theses\.fr/([A-Za-z0-9]+)")


def extract_nnt_from_location(loc: OpenalexLocation) -> str | None:
    """Renvoie le NNT d'une localisation theses.fr : d'après `location.id` (`pmh:{NNT}`), à défaut sa page (`…/theses.fr/{NNT}/…`)."""
    if loc.location_id:
        m = _PMH_NNT_RE.match(loc.location_id)
        if m:
            return NNT.normalize(m.group(1))
    if loc.landing_page_url:
        m = _THESES_FR_URL_RE.search(loc.landing_page_url)
        if m:
            return NNT.normalize(m.group(1))
    return None


def url_identifiers(urls: list[str]) -> list[SourceIdentifier]:
    """Renvoie les identifiants secondaires exposés dans une liste d'URLs, dans leur ordre : `hal_id` (préfixes `hal-`/`tel-`/`halshs-`…), NNT (URLs `theses.fr/<NNT>`), PMID (PubMed), DOI d'un dépôt arXiv et numéro de fiche du CERN Document Server."""
    identifiers: list[SourceIdentifier] = []
    for url in urls:
        for id_type, value in (
            (SourceIdentifierType.HAL_ID, HALId.normalize(url)),
            (
                SourceIdentifierType.NNT,
                m.group(1) if (m := _THESES_FR_URL_RE.search(url)) else None,
            ),
            (SourceIdentifierType.PMID, PMID.normalize(url)),
            (SourceIdentifierType.DOI, arxiv_doi(url)),
            (SourceIdentifierType.CDS, CdsId.normalize(url)),
        ):
            if value:
                identifiers.append(SourceIdentifier(id_type, value, SourceIdentifierRole.SECONDARY))
    return identifiers


def openalex_derived_identifier(primary: OpenalexLocation | None) -> SourceIdentifier | None:
    """Renvoie l'identifiant de la localisation principale d'un work : NNT d'une localisation theses.fr, sinon premier `hal_id`, DOI, PMID ou DOI d'un dépôt arXiv de sa page ou de son identifiant de localisation."""
    if primary is None:
        return None
    if is_theses_fr_location(primary) and (nnt := extract_nnt_from_location(primary)):
        return SourceIdentifier(SourceIdentifierType.NNT, nnt, SourceIdentifierRole.DERIVED)
    for id_type, extract in (
        (SourceIdentifierType.HAL_ID, HALId.normalize),
        (SourceIdentifierType.DOI, extract_doi_from_url),
        (SourceIdentifierType.PMID, PMID.normalize),
        (SourceIdentifierType.DOI, arxiv_doi),
    ):
        for raw in (primary.landing_page_url, primary.location_id):
            if value := extract(raw):
                return SourceIdentifier(id_type, value, SourceIdentifierRole.DERIVED)
    return None
