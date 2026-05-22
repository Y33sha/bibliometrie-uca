"""Aggregate root ``Publisher`` — entité métier d'un éditeur.

Identité = `id` (clé surrogate). Identifiant naturel : `name`
(via la normalisation côté `publisher_name_forms`).

La logique métier touchant aux éditeurs (matching, fusion, détection
predatory) vit ici. Scaffolding a minima : pas d'invariants métier
identifiés aujourd'hui, à enrichir si nécessaire.

`PUBLISHER_TYPES` doit rester synchronisé avec l'enum SQL `publisher_type` —
test de cohérence dans `tests/integration/test_scenarios.py::TestPublisherTypesEnum`.
"""

from dataclasses import dataclass
from typing import Literal

PublisherType = Literal[
    "commercial",
    "learned_society",
    "academic_institution",
    "repository",
    "aggregator",
    "unknown",
]
PUBLISHER_TYPES: tuple[PublisherType, ...] = (
    "commercial",
    "learned_society",
    "academic_institution",
    "repository",
    "aggregator",
    "unknown",
)
PUBLISHER_TYPES_SET: frozenset[str] = frozenset(PUBLISHER_TYPES)

# Labels FR de chaque valeur d'enum, source de vérité côté Python pour les
# affichages UI (dropdowns admin, colonnes/badges des pages publiques).
# Exposés au frontend via `/api/publisher-types`.
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
    is_predatory: bool = False
    publisher_type: str = "unknown"  # une des valeurs de PUBLISHER_TYPES
