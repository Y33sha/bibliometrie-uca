"""Aggregate root `Publisher` — entité métier d'un éditeur.

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

# Mapping ROR `types` → notre `publisher_type`. ROR v2 expose `types`
# comme une LISTE (ex. `['company', 'funder']`). On applique le mapping
# par ordre de précédence : le premier ROR type qui a une correspondance
# l'emporte. `funder` est volontairement absent — c'est presque toujours
# un type secondaire qui bruite la liste (un éditeur qui finance aussi
# de la recherche). Cf. audit Phase 3 (`audit_ror_types_for_publishers`).
#
# Décisions tranchées à l'audit :
# - `government` exclu (ex. European Commission, CDC, Académies nationales
#   — pas des academic_institution).
# - `facility`, `other`, `healthcare` skip — bruit (INSEE, Sciences Po,
#   Mathematical Society of America fourrent dans `other`/`facility`, à
#   arbitrer manuellement via l'UI admin).
# - `nonprofit` → `learned_society` : couvre les vraies sociétés savantes
#   (American Meteorological Society…) ET les éditeurs nonprofit (eLife,
#   BioOne). L'amalgame est assumé — on préfère un signal raisonnable à
#   un skip.
_ROR_TYPE_TO_PUBLISHER_TYPE: list[tuple[str, PublisherType]] = [
    ("education", "academic_institution"),
    ("archive", "repository"),
    ("company", "commercial"),
    ("nonprofit", "learned_society"),
]


def map_ror_types(ror_types: list[str]) -> PublisherType | None:
    """Mappe une liste de ROR `types` vers notre enum `publisher_type`.

    Renvoie `None` quand aucun ROR type de la liste n'a de mapping
    défini (`government`, `facility`, `other`, `healthcare`, ou
    seulement `funder`) — le caller doit alors ne pas écrire.
    """
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
