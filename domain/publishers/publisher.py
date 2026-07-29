"""Aggregate root `Publisher` — un éditeur.

Identité = `id` (clé surrogate). Identifiant naturel : `name`, via la normalisation de `publisher_name_forms`.

`PUBLISHER_TYPES` reste synchronisé avec l'enum SQL `publisher_type` — cohérence vérifiée par `tests/integration/test_scenarios.py::TestPgEnumsMatchDb`.
"""

from dataclasses import dataclass
from enum import StrEnum


class PublisherType(StrEnum):
    """Type d'éditeur — les membres portent les libellés de l'enum PostgreSQL `publisher_type`."""

    COMMERCIAL = "commercial"
    LEARNED_SOCIETY = "learned_society"
    ACADEMIC_INSTITUTION = "academic_institution"
    REPOSITORY = "repository"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"


PUBLISHER_TYPES: tuple[PublisherType, ...] = tuple(PublisherType)
PUBLISHER_TYPES_SET: frozenset[str] = frozenset(PublisherType)

# Labels FR des valeurs d'enum, source de vérité Python pour l'UI (dropdowns admin, badges publics), exposés via `/api/publishers/types`.
PUBLISHER_TYPE_LABELS_FR: dict[PublisherType, str] = {
    PublisherType.COMMERCIAL: "Éditeur commercial",
    PublisherType.LEARNED_SOCIETY: "Société savante",
    PublisherType.ACADEMIC_INSTITUTION: "Établissement d'enseignement",
    PublisherType.REPOSITORY: "Archive / dépôt",
    PublisherType.AGGREGATOR: "Agrégateur",
    PublisherType.UNKNOWN: "Type inconnu",
}


@dataclass(slots=True)
class Publisher:
    """Éditeur (aggregate root)."""

    id: int | None
    name: str
    country: str | None = None
    openalex_id: str | None = None
    publisher_type: PublisherType = PublisherType.UNKNOWN
