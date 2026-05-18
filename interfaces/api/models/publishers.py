"""Modèles Pydantic pour les éditeurs (publishers).

Les DTOs de retour des query services (`PublisherListItem`,
`PublisherListResponse`, `PublisherBasic`) vivent dans
`application/ports/api/publishers_queries.py` (cf. chantier
`CODE_typage-projections-strict` Phase 4).
"""

from pydantic import BaseModel


class PublisherUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    doi_prefix: str | None = None
    is_predatory: bool | None = None
    notes: str | None = None
