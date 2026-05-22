"""Modèles Pydantic pour les éditeurs (publishers).

Les DTOs de retour des query services (`PublisherListItem`,
`PublisherListResponse`, `PublisherDetailResponse`,
`PublisherDashboardResponse`) vivent dans
`application/ports/api/publishers_queries.py` (cf. chantier
`CODE_typage-projections-strict` Phase 4).
"""

from pydantic import BaseModel


class PublisherUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    is_predatory: bool | None = None
    publisher_type: str | None = None
