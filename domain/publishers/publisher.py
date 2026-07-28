"""Vocabulaire métier des éditeurs — type d'éditeur.

`PublisherType` porte le jeu de valeurs de l'enum PostgreSQL `publisher_type`, avec ses libellés FR pour l'UI. L'édition d'un éditeur passe par le CRUD sélectif du port `publisher_repository` (`PublisherUpdate`), la lecture par les read-models. `PublisherType` reste synchronisé avec l'enum SQL — cohérence vérifiée par `tests/integration/test_scenarios.py::TestPgEnumsMatchDb`.
"""

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

# Labels FR des valeurs d'enum, source de vérité Python pour l'UI (dropdowns admin, badges publics), exposés via `/api/publishers/types`.
PUBLISHER_TYPE_LABELS_FR: dict[PublisherType, str] = {
    "commercial": "Éditeur commercial",
    "learned_society": "Société savante",
    "academic_institution": "Établissement d'enseignement",
    "repository": "Archive / dépôt",
    "aggregator": "Agrégateur",
    "unknown": "Type inconnu",
}
