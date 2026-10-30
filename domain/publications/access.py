"""Liens d'accès d'une publication : ses copies ouvertes, une par plateforme.

Une copie se classe par sa version (éditeur, acceptée, soumise, inconnue), puis par l'ordre d'arrivée de son enregistrement source. Chaque plateforme donne sa meilleure copie ; une copie sans plateforme se range sous l'hôte de son URL. Quand une plateforme décrit elle-même la publication (HAL pour HAL), seule sa description décide de l'ouverture de ses copies.

Seule une copie à adresse `http` ou `https` compte. La meilleure copie donne l'adresse d'accès. Une copie désignée par le DOI de la publication est absente des liens : le DOI s'affiche à part. Une copie désignée par un autre DOI figure parmi les liens seulement si une plateforme l'héberge.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from domain.platforms.registry import KnownPlatform
from domain.publications.metadata import OA_OPEN_STATUSES, OaStatus

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
    """Nom de la plateforme qui héberge la copie : celui de la liste pour une plateforme connue, sinon celui donné par la source."""
    known_platform: KnownPlatform | None
    """Plateforme de la liste qui héberge la copie (`known_platform_of_copy`)."""
    described_by_platform: bool
    """La copie vient de l'enregistrement source donné par la plateforme elle-même."""
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


def _label(copy: Copy) -> str:
    if copy.known_platform:
        return copy.known_platform.name
    return copy.platform or _host(copy).removeprefix("www.")


def _listed(copy: Copy, doi: str | None) -> bool:
    """Vrai si la copie figure parmi les liens."""
    if _host(copy) not in _DOI_HOSTS:
        return True
    target = unquote(urlsplit(copy.url).path).lstrip("/").lower()
    return copy.platform is not None and target != (doi or "").lower()


def _rank(copy: Copy) -> tuple[int, int]:
    return _VERSION_RANK.get(copy.version or "", _UNKNOWN_VERSION_RANK), copy.arrival


def access(copies: Iterable[Copy], *, doi: str | None) -> Access:
    """Calcule l'adresse d'accès et les liens d'accès d'une publication de DOI `doi`."""
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
            AccessLink(label, copy.url, copy.known_platform is not None)
            for label, copy in best.items()
        ],
    )


def access_url(best_copy_url: str | None, *, oa_status: str | None, doi: str | None) -> str | None:
    """Renvoie le lien d'accès d'une publication : la meilleure copie, à défaut la page du DOI d'une publication ouverte. `None` pour une publication fermée ou sous embargo."""
    if oa_status in (OaStatus.CLOSED, OaStatus.EMBARGOED):
        return None
    if best_copy_url:
        return best_copy_url
    if oa_status in OA_OPEN_STATUSES and doi:
        return f"https://doi.org/{doi}"
    return None
