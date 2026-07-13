"""Aggregate root `Publisher` — un éditeur.

Identité = `id` (clé surrogate). Identifiant naturel : `name`, via la normalisation de `publisher_name_forms`.

`PUBLISHER_TYPES` reste synchronisé avec l'enum SQL `publisher_type` — cohérence vérifiée par `tests/integration/test_scenarios.py::TestPublisherTypesEnum`.
"""

from dataclasses import dataclass
from typing import Literal, get_args

PublisherType = Literal[
    "commercial",
    "learned_society",
    "academic_institution",
    "repository",
    "aggregator",
    "unknown",
]
PUBLISHER_TYPES: tuple[PublisherType, ...] = get_args(PublisherType)
PUBLISHER_TYPES_SET: frozenset[str] = frozenset(PUBLISHER_TYPES)

# Labels FR des valeurs d'enum, source de vérité Python pour l'UI (dropdowns admin, badges publics), exposés via `/api/publisher-types`.
PUBLISHER_TYPE_LABELS_FR: dict[PublisherType, str] = {
    "commercial": "Éditeur commercial",
    "learned_society": "Société savante",
    "academic_institution": "Établissement d'enseignement",
    "repository": "Archive / dépôt",
    "aggregator": "Agrégateur",
    "unknown": "Type inconnu",
}


@dataclass(slots=True)
class Publisher:
    """Éditeur (aggregate root)."""

    id: int | None
    name: str
    country: str | None = None
    openalex_id: str | None = None
    ror: str | None = None
    is_predatory: bool = False
    publisher_type: PublisherType = "unknown"
