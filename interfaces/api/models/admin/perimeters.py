"""Modèles Pydantic pour les périmètres (CRUD + structures membres)."""

from pydantic import BaseModel


class PerimeterStructureItem(BaseModel):
    id: int
    name: str
    acronym: str | None
    code: str


class PerimeterOut(BaseModel):
    """Périmètre + ses structures racines (résolues + comptage effectif)."""

    id: int
    code: str
    name: str
    description: str | None
    structure_ids: list[int]
    structures: list[PerimeterStructureItem]
    structure_count: int


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
