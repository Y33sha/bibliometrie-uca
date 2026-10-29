"""Plateformes qui hébergent des publications."""

from enum import StrEnum
from urllib.parse import urlparse


class PlatformType(StrEnum):
    """Type de plateforme. Reflet du type PostgreSQL `platform_type`.

    Une archive et un entrepôt de données sont des `REPOSITORY`, que le type de document distingue. Un document déposé sur un serveur de preprints est un preprint.
    """

    REPOSITORY = "repository"
    PREPRINT_SERVER = "preprint_server"
    PUBLISHER_PLATFORM = "publisher_platform"
    UNKNOWN = "unknown"


PLATFORM_TYPES: tuple[PlatformType, ...] = tuple(PlatformType)

_CATALOG_DOMAINS = frozenset({"doaj.org"})


def is_catalog_record(url: str) -> bool:
    """Vrai si l'URL mène à la fiche d'un catalogue, qui décrit le document sans en donner le texte. Une telle fiche est exclue des localisations."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host in _CATALOG_DOMAINS
