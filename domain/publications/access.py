"""Liens d'accès d'une publication : ses copies ouvertes, une par plateforme.

Une copie se classe par sa version (éditeur, acceptée, soumise, inconnue), puis par l'ordre d'arrivée de son enregistrement source. Chaque plateforme donne sa meilleure copie ; une copie sans plateforme se range sous l'hôte de son URL. Quand une plateforme décrit elle-même la publication (HAL pour HAL), sa description décide de l'ouverture de ses copies : les copies que les autres sources lui attribuent sont écartées.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

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
    described_by_platform: bool
    """La copie vient de l'enregistrement source que la plateforme donne elle-même."""
    arrival: int
    """Ordre d'arrivée de l'enregistrement source."""


@dataclass(frozen=True, slots=True)
class AccessLink:
    label: str
    url: str


def _label(copy: Copy) -> str:
    host = urlsplit(copy.url).hostname or copy.url
    return copy.platform or host.removeprefix("www.")


def _rank(copy: Copy) -> tuple[int, int]:
    return _VERSION_RANK.get(copy.version or "", _UNKNOWN_VERSION_RANK), copy.arrival


def access_links(copies: Iterable[Copy]) -> list[AccessLink]:
    """Meilleure copie ouverte de chaque plateforme, la meilleure en tête."""
    copies = list(copies)
    self_described = {c.platform for c in copies if c.described_by_platform}
    open_copies = [
        c
        for c in copies
        if c.is_oa and (c.described_by_platform or c.platform not in self_described)
    ]
    best: dict[str, Copy] = {}
    for copy in sorted(open_copies, key=_rank):
        best.setdefault(_label(copy), copy)
    return [AccessLink(label, copy.url) for label, copy in best.items()]
