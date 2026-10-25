"""Liens d'accès d'une publication : ses copies ouvertes, une par plateforme.

Une copie se classe par sa version (éditeur, acceptée, soumise, inconnue), puis par l'ordre d'arrivée de son enregistrement source. Chaque plateforme donne sa meilleure copie ; une copie sans plateforme se range sous l'hôte de son URL. Quand une plateforme décrit elle-même la publication (HAL pour HAL), sa description décide de l'ouverture de ses copies : les copies que les autres sources lui attribuent sont écartées.

Une plateforme du registre (`domain.platforms.registry`) est connue de l'interface ; les autres dépôts sont nommés par la source ou par l'hôte.

Seule une copie à adresse `http` ou `https` compte : l'adresse vient des sources, et alimente un lien. La meilleure copie est l'adresse d'accès. Une copie désignée par le DOI de la publication peut l'être, mais ne figure pas parmi les liens : le DOI est affiché à part.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from domain.platforms.registry import KNOWN_PLATFORMS

_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org"})
_WEB_SCHEMES = frozenset({"http", "https"})
_VERSION_RANK = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}
_UNKNOWN_VERSION_RANK = len(_VERSION_RANK)
_KNOWN_PLATFORM_NAMES = frozenset(p.name for p in KNOWN_PLATFORMS)


@dataclass(frozen=True, slots=True, kw_only=True)
class Copy:
    """Localisation d'un enregistrement source de la publication."""

    url: str
    version: str | None
    is_oa: bool | None
    platform: str | None
    """Nom de la plateforme qui héberge la copie."""
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
    """Meilleure copie ouverte de chaque plateforme, la meilleure en tête, hors copies désignées par le DOI."""


def _host(copy: Copy) -> str:
    return urlsplit(copy.url).hostname or copy.url


def _label(copy: Copy) -> str:
    return copy.platform or _host(copy).removeprefix("www.")


def _rank(copy: Copy) -> tuple[int, int]:
    return _VERSION_RANK.get(copy.version or "", _UNKNOWN_VERSION_RANK), copy.arrival


def access(copies: Iterable[Copy]) -> Access:
    """Adresse d'accès et liens d'accès d'une publication."""
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
        if _host(copy) not in _DOI_HOSTS:
            best.setdefault(_label(copy), copy)
    return Access(
        url=ranked[0].url if ranked else None,
        links=[
            AccessLink(label, copy.url, copy.platform in _KNOWN_PLATFORM_NAMES)
            for label, copy in best.items()
        ],
    )
