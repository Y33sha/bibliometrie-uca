"""Re-export des DTOs Subjects.

Les modèles vivent désormais dans `application.subjects.dtos` (chantier `CODE_typage-projections-strict` Phase 4 : sweep DTO par feature). Ce module reste pour les imports historiques `from interfaces.api.models import SubjectXxx`.
"""

from application.subjects.dtos import (
    SubjectDetailResponse,
    SubjectFrequency,
    SubjectListItem,
    SubjectListResponse,
    SubjectNeighborOut,
    SubjectOntologyEntry,
    SubjectOut,
)

__all__ = [
    "SubjectDetailResponse",
    "SubjectFrequency",
    "SubjectListItem",
    "SubjectListResponse",
    "SubjectNeighborOut",
    "SubjectOntologyEntry",
    "SubjectOut",
]
