"""Éditeurs et types d'éditeur."""

from dataclasses import dataclass
from enum import StrEnum


class PublisherType(StrEnum):
    """Type d'éditeur. Reflet du type PostgreSQL `publisher_type`."""

    COMMERCIAL = "commercial"
    LEARNED_SOCIETY = "learned_society"
    ACADEMIC_INSTITUTION = "academic_institution"
    REPOSITORY = "repository"
    AGGREGATOR = "aggregator"
    MEDIA = "media"
    UNKNOWN = "unknown"


PUBLISHER_TYPES: tuple[PublisherType, ...] = tuple(PublisherType)
PUBLISHER_TYPES_SET: frozenset[str] = frozenset(PublisherType)

# Libellés français des types d'éditeur, servis à l'interface par `/api/publishers/types`.
PUBLISHER_TYPE_LABELS_FR: dict[PublisherType, str] = {
    PublisherType.COMMERCIAL: "Éditeur commercial",
    PublisherType.LEARNED_SOCIETY: "Société savante",
    PublisherType.ACADEMIC_INSTITUTION: "Établissement d'enseignement",
    PublisherType.REPOSITORY: "Archive / dépôt",
    PublisherType.AGGREGATOR: "Agrégateur",
    PublisherType.MEDIA: "Média",
    PublisherType.UNKNOWN: "Type inconnu",
}


@dataclass(slots=True)
class Publisher:
    id: int | None
    name: str
    country: str | None = None
    openalex_id: str | None = None
    publisher_type: PublisherType = PublisherType.UNKNOWN
