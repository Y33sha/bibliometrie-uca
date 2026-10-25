"""Liens d'accès d'une publication : ses copies ouvertes, une par plateforme.

Une copie se classe par sa version (éditeur, acceptée, soumise, inconnue), puis par l'ordre d'arrivée de son enregistrement source. Chaque plateforme donne sa meilleure copie ; une copie sans plateforme se range sous l'hôte de son URL. Quand une plateforme décrit elle-même la publication (HAL pour HAL), sa description décide de l'ouverture de ses copies : les copies que les autres sources lui attribuent sont écartées.

Une plateforme du registre (`domain.platforms.registry`) se reconnaît par sa source OpenAlex et porte le nom du registre. Une autre plateforme porte le nom que lui donne la source.

Seule une copie à adresse `http` ou `https` compte : l'adresse vient des sources, et alimente un lien. La meilleure copie est l'adresse d'accès. Une copie désignée par le DOI de la publication peut l'être, mais ne figure pas parmi les liens : le DOI est affiché à part. Une copie désignée par un autre DOI figure parmi les liens seulement si une plateforme l'héberge.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from domain.platforms.registry import KnownPlatform, known_platform_of_source

_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org"})
_WEB_SCHEMES = frozenset({"http", "https"})
_VERSION_RANK = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}
_UNKNOWN_VERSION_RANK = len(_VERSION_RANK)


@dataclass(frozen=True, slots=True, kw_only=True)
class Copy:
    """Localisation d'un enregistrement source de la publication."""

    url: str
    version: str | None
    is_oa: bool | None
    platform: str | None
    """Nom de la plateforme qui héberge la copie."""
    platform_openalex_id: str | None
    """Source OpenAlex de la plateforme."""
    described_by_platform: bool
    """La copie vient de l'enregistrement source que la plateforme donne elle-même."""
    arrival: int
    """Ordre d'arrivée de l'enregistrement source."""


@dataclass(frozen=True, slots=True)
class AccessLink:
    label: str
    url: str
    known: bool
    """La copie est hébergée par une plateforme du registre."""


@dataclass(frozen=True, slots=True)
class Access:
    url: str | None
    """Adresse de la meilleure copie ouverte."""
    links: list[AccessLink]
    """Meilleure copie ouverte de chaque plateforme, la meilleure en tête."""


def _host(copy: Copy) -> str:
    return urlsplit(copy.url).hostname or copy.url


def _known_platform(copy: Copy) -> KnownPlatform | None:
    if copy.platform_openalex_id is None:
        return None
    return known_platform_of_source(copy.platform_openalex_id)


def _label(copy: Copy) -> str:
    if known := _known_platform(copy):
        return known.name
    return copy.platform or _host(copy).removeprefix("www.")


def _listed(copy: Copy, doi: str | None) -> bool:
    """La copie figure parmi les liens : elle est désignée par une adresse autre qu'un DOI, ou par un autre DOI que celui de la publication sur une plateforme."""
    if _host(copy) not in _DOI_HOSTS:
        return True
    target = unquote(urlsplit(copy.url).path).lstrip("/").lower()
    return copy.platform is not None and target != (doi or "").lower()


def _rank(copy: Copy) -> tuple[int, int]:
    return _VERSION_RANK.get(copy.version or "", _UNKNOWN_VERSION_RANK), copy.arrival


def access(copies: Iterable[Copy], *, doi: str | None) -> Access:
    """Adresse d'accès et liens d'accès d'une publication de DOI `doi`."""
    copies = list(copies)
    self_described = {c.platform for c in copies if c.described_by_platform}
    open_copies = [
        c
        for c in copies
        if c.is_oa
        and urlsplit(c.url).scheme in _WEB_SCHEMES
        and (c.described_by_platform or c.platform not in self_described)
    ]
    ranked = sorted(open_copies, key=_rank)
    best: dict[str, Copy] = {}
    for copy in ranked:
        if _listed(copy, doi):
            best.setdefault(_label(copy), copy)
    return Access(
        url=ranked[0].url if ranked else None,
        links=[
            AccessLink(label, copy.url, _known_platform(copy) is not None)
            for label, copy in best.items()
        ],
    )
