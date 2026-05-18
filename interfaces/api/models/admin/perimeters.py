"""Modèles Pydantic (bodies HTTP) pour les périmètres.

Les DTOs de retour des query services (`PerimeterOut`, `PerimeterStructureItem`)
vivent dans `application/ports/api/perimeters_queries.py` (cf. chantier
`CODE_typage-projections-strict` Phase 4).
"""

from pydantic import BaseModel


class AddPerimeterStructure(BaseModel):
    structure_id: int


class PerimeterCreate(BaseModel):
    code: str
    name: str
    description: str | None = None


class PerimeterUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    structure_ids: list[int] | None = None
