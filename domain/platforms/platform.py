"""Plateforme qui héberge des publications, et localisations qui en relèvent.

`PLATFORM_TYPES` reste synchronisé avec l'enum SQL `platform_type`.
"""

from enum import StrEnum
from urllib.parse import urlparse


class PlatformType(StrEnum):
    """Type de plateforme — les membres portent les libellés de l'enum PostgreSQL `platform_type`.

    Une archive et un entrepôt de données sont des `REPOSITORY`, que le type de document distingue. Un document déposé sur un serveur de preprints est un preprint ; un entrepôt ne dit rien du type de ses documents.
    """

    REPOSITORY = "repository"
    PREPRINT_SERVER = "preprint_server"
    PUBLISHER_PLATFORM = "publisher_platform"
    UNKNOWN = "unknown"


PLATFORM_TYPES: tuple[PlatformType, ...] = tuple(PlatformType)

_CATALOG_DOMAINS = frozenset({"doaj.org"})
"""Catalogues dont la page décrit un document sans en donner le texte."""


def is_catalog_record(url: str) -> bool:
    """Vrai quand `url` mène à la fiche d'un catalogue, sans copie du texte : ce n'est pas une localisation."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host in _CATALOG_DOMAINS
