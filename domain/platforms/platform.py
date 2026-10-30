"""Plateformes qui hébergent des publications."""

from enum import StrEnum

from domain.urls import is_on_site


class PlatformType(StrEnum):
    """Type de plateforme. Reflet du type PostgreSQL `platform_type`.

    Une archive et un entrepôt de données sont des `REPOSITORY`, que le type de document distingue. Un document déposé sur un serveur de preprints est un preprint.
    """

    REPOSITORY = "repository"
    PREPRINT_SERVER = "preprint_server"
    PUBLISHER_PLATFORM = "publisher_platform"
    UNKNOWN = "unknown"


PLATFORM_TYPES: tuple[PlatformType, ...] = tuple(PlatformType)

_DESCRIPTIVE_PAGE_SITES = (
    "doaj.org",
    "doabooks.org",
    "pubmed.ncbi.nlm.nih.gov",
    "eprints.gla.ac.uk/view",
)
"""Pages du DOAJ, du DOAB et de PubMed, listes de l'archive de l'université de Glasgow."""


def is_descriptive_page(url: str) -> bool:
    """Vrai si l'URL mène à une page descriptive : elle décrit le document sans en donner le texte. Une telle page est exclue des localisations."""
    return any(is_on_site(url, site) for site in _DESCRIPTIVE_PAGE_SITES)
