"""Aggregate root `Publisher` — un éditeur.

Identité = `id` (clé surrogate). Identifiant naturel : `name`, via la normalisation de `publisher_name_forms`.

`PUBLISHER_TYPES` reste synchronisé avec l'enum SQL `publisher_type` — cohérence vérifiée par `tests/integration/test_scenarios.py::TestPublisherTypesEnum`.
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

# Labels FR des valeurs d'enum, source de vérité Python pour l'UI (dropdowns admin, badges publics), exposés via `/api/publisher-types`.
PUBLISHER_TYPE_LABELS_FR: dict[PublisherType, str] = {
    "commercial": "Éditeur commercial",
    "learned_society": "Société savante",
    "academic_institution": "Établissement d'enseignement",
    "repository": "Archive / dépôt",
    "aggregator": "Agrégateur",
    "unknown": "Type inconnu",
}

# Mapping ROR `types` (v2 : une LISTE, ex. `['company', 'funder']`) → `publisher_type`, par ordre de précédence : le premier type ROR mappé l'emporte.
# Absents volontairement : `funder` (type secondaire bruité), `government` (European Commission, académies… pas des academic_institution), `facility` / `other` / `healthcare` (bruit, à arbitrer en admin).
# `nonprofit` → `learned_society` couvre sociétés savantes et éditeurs nonprofit (eLife, BioOne) : amalgame assumé, préféré à un skip.
_ROR_TYPE_TO_PUBLISHER_TYPE: list[tuple[str, PublisherType]] = [
    ("education", "academic_institution"),
    ("archive", "repository"),
    ("company", "commercial"),
    ("nonprofit", "learned_society"),
]


def map_ror_types(ror_types: list[str]) -> PublisherType | None:
    """Mappe une liste de ROR `types` vers l'enum `publisher_type`, ou `None` si aucun type de la liste n'est mappé (`government`, `facility`, `other`, `healthcare`, ou `funder` seul)."""
    for ror_type, publisher_type in _ROR_TYPE_TO_PUBLISHER_TYPE:
        if ror_type in ror_types:
            return publisher_type
    return None


@dataclass(slots=True)
class Publisher:
    """Éditeur (aggregate root)."""

    id: int | None
    name: str
    country: str | None = None
    openalex_id: str | None = None
    ror: str | None = None
    is_predatory: bool = False
    publisher_type: str = "unknown"  # une des valeurs de PUBLISHER_TYPES
