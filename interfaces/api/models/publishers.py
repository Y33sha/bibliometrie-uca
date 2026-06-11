"""Modèles Pydantic pour les éditeurs (publishers).

Les DTOs de retour des query services (`PublisherListItem`,
`PublisherListResponse`, `PublisherDetailResponse`,
`PublisherDashboardResponse`) vivent dans
`application/ports/api/publishers_queries.py` (cf. chantier
`CODE_typage-projections-strict` Phase 4).
"""

from pydantic import BaseModel, field_validator


class PublisherUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    is_predatory: bool | None = None
    publisher_type: str | None = None

    @field_validator("country")
    @classmethod
    def _country_lowercase(cls, v: str | None) -> str | None:
        # Code pays canonique en minuscule (cf. countries.code / addresses.countries).
        return v.lower() if v else v
