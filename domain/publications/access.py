"""Liens d'accès d'une publication : ses copies ouvertes, une par plateforme.

Seules les copies ouvertes comptent (`open_copies`). La copie de l'éditeur, désignée par le DOI de la publication, passe en tête, puis les autres copies en version éditeur, hors preprint. Suivent les copies des plateformes à icône (`KnownPlatform.icon`), puis les autres. Dans chaque groupe, les copies d'un preprint passent après les autres (`Copy.of_preprint`). Une copie se classe ensuite par sa version (éditeur, acceptée, soumise, inconnue), puis par l'ordre d'arrivée de son enregistrement source. Chaque plateforme donne sa meilleure copie ; une copie sans plateforme se range sous l'hôte de son URL.

La meilleure copie donne l'adresse d'accès. Une copie désignée par un DOI figure parmi les liens quand une archive ou un serveur de preprints l'héberge (Zenodo), ou quand une autre plateforme l'héberge sous un autre DOI que celui de la publication. Le DOI de la publication chez son éditeur s'affiche à part.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from domain.documents.doc_types import DocType
from domain.documents.identifiers import HALId
from domain.documents.licenses import License
from domain.platforms.platform import ARCHIVE_TYPES, PlatformType
from domain.platforms.registry import (
    HAL,
    KnownPlatform,
    is_fully_open,
    known_platform_of_copy,
    platform_type_of_copy,
)
from domain.publications.oa_status import OA_OPEN_STATUSES, OaStatus
from domain.sources.registry import Source

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
    platform_type: PlatformType | None
    """Type de la plateforme : celui de la liste (`platform_type_of_copy`), à défaut celui donné par la source."""
    license: License | None
    described_by_platform: bool
    """La copie vient de l'enregistrement source donné par la plateforme elle-même."""
    arrival: int
    """Ordre d'arrivée de l'enregistrement source ; zéro pour la copie de l'URL de résolution du DOI."""
    preprint_record: bool = False
    """La copie vient d'un enregistrement source typé preprint."""

    @classmethod
    def of_location(
        cls,
        url: str,
        *,
        version: str | None,
        declared_oa: bool | None,
        arrival: int,
        embargoed: bool = False,
        license: License | None = None,  # noqa: A002 — nom du champ de la copie
        source_platform: str | None = None,
        source_platform_type: PlatformType | None = None,
        platform_openalex_id: str | None = None,
        record_source: str | None = None,
        record_doc_type: str | None = None,
    ) -> Copy:
        """Renvoie la copie d'une localisation d'un enregistrement source.

        La plateforme de la liste donne son nom et son type, à défaut ceux donnés par la source. Une copie sous embargo est fermée. La copie HAL d'un enregistrement HAL est décrite par sa plateforme. Une copie garde le type preprint de son enregistrement source.

        Args:
            declared_oa: ouverture déclarée par la source.
            platform_openalex_id: identifiant OpenAlex de la plateforme donnée par la source.
            record_source: source de l'enregistrement source.
            record_doc_type: type de document de l'enregistrement source.
        """
        known = known_platform_of_copy(url, platform_openalex_id)
        return cls(
            url=url,
            version=version,
            is_oa=declared_oa and not embargoed,
            platform=known.name if known else source_platform,
            known_platform=known,
            platform_type=platform_type_of_copy(url, platform_openalex_id) or source_platform_type,
            license=license,
            described_by_platform=record_source == Source.HAL and known is HAL,
            arrival=arrival,
            preprint_record=record_doc_type == DocType.PREPRINT,
        )

    @property
    def of_preprint(self) -> bool:
        """Vrai pour la copie d'un enregistrement source preprint, ou d'un serveur de preprints."""
        return self.preprint_record or self.platform_type is PlatformType.PREPRINT_SERVER


@dataclass(frozen=True, slots=True)
class AccessLink:
    label: str
    url: str
    icon: str | None
    """Icône de la plateforme qui héberge la copie (`KnownPlatform.icon`)."""


@dataclass(frozen=True, slots=True)
class Access:
    url: str | None
    """Adresse de la meilleure copie ouverte."""
    links: list[AccessLink]
    """Meilleure copie ouverte de chaque plateforme, la meilleure en tête."""


def _host(copy: Copy) -> str:
    return urlsplit(copy.url).hostname or copy.url


def _label(copy: Copy) -> str:
    return copy.platform or _host(copy).removeprefix("www.")


def _icon(copy: Copy) -> str | None:
    return copy.known_platform.icon if copy.known_platform else None


def _doi_target(copy: Copy) -> str | None:
    """Renvoie le DOI désigné par une copie à l'adresse de doi.org, en minuscules, ou `None` pour une autre adresse."""
    if _host(copy) not in _DOI_HOSTS:
        return None
    return unquote(urlsplit(copy.url).path).lstrip("/").lower()


def _from_publisher(copy: Copy, doi: str | None) -> bool:
    """Vrai pour la copie de l'éditeur : la page du DOI de la publication, ou l'URL de résolution de ce DOI."""
    return copy.arrival == 0 or (doi is not None and _doi_target(copy) == doi.lower())


def _listed(copy: Copy, doi: str | None) -> bool:
    """Vrai si la copie figure parmi les liens."""
    target = _doi_target(copy)
    if target is None or copy.platform_type in ARCHIVE_TYPES:
        return True
    return copy.platform is not None and target != (doi or "").lower()


def _rank(copy: Copy, doi: str | None) -> tuple[bool, bool, bool, bool, int, int]:
    return (
        not _from_publisher(copy, doi),
        copy.version != "publishedVersion" or copy.of_preprint,
        _icon(copy) is None,
        copy.of_preprint,
        _VERSION_RANK.get(copy.version or "", _UNKNOWN_VERSION_RANK),
        copy.arrival,
    )


def registered_url_copy(url: str) -> Copy | None:
    """Renvoie la copie ouverte désignée par l'URL de résolution d'un DOI, ou `None`.

    L'URL d'une plateforme en accès libre intégral (`is_fully_open`) donne une copie de version inconnue. À défaut, une URL dont le chemin finit par `.pdf` donne une copie en version de l'éditeur.
    """
    if is_fully_open(url):
        version = None
    elif urlsplit(url).path.lower().endswith(".pdf"):
        version = "publishedVersion"
    else:
        return None
    return Copy.of_location(url, version=version, declared_oa=True, arrival=0)


def open_copies(copies: Iterable[Copy]) -> list[Copy]:
    """Renvoie les copies ouvertes, à adresse `http` ou `https`. Quand HAL décrit lui-même un dépôt, seule sa description décide de l'ouverture des copies de ce dépôt."""
    copies = list(copies)
    self_described = {
        hal_id for c in copies if c.described_by_platform and (hal_id := HALId.normalize(c.url))
    }
    return [
        c
        for c in copies
        if c.is_oa
        and urlsplit(c.url).scheme in _WEB_SCHEMES
        and (c.described_by_platform or HALId.normalize(c.url) not in self_described)
    ]


def access(copies: Iterable[Copy], *, doi: str | None) -> Access:
    """Calcule l'adresse d'accès et les liens d'accès d'une publication de DOI `doi`."""
    ranked = sorted(open_copies(copies), key=lambda copy: _rank(copy, doi))
    best: dict[str, Copy] = {}
    for copy in ranked:
        if _listed(copy, doi):
            best.setdefault(_label(copy), copy)
    return Access(
        url=ranked[0].url if ranked else None,
        links=[AccessLink(label, copy.url, _icon(copy)) for label, copy in best.items()],
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
