"""Modèles de réponse : lectures sur les périmètres et l'établissement servi par l'instance."""

from pydantic import BaseModel


class PerimeterStructureItem(BaseModel):
    id: int
    name: str
    acronym: str | None
    code: str


class PerimeterOut(BaseModel):
    """Un périmètre : ses structures racines, en identifiants et résolues, et `structure_count`, le nombre de structures des racines et de leurs sous-structures. `is_persons` désigne le périmètre des personnes, celui de la liste publique des structures."""

    id: int
    code: str
    name: str
    root_structure_ids: list[int]
    structures: list[PerimeterStructureItem]
    structure_count: int
    is_persons: bool


class PerimeterCountryOut(BaseModel):
    """Pays d'organisations ROR des structures du périmètre des personnes."""

    code: str
    name: str | None


class InstitutionOut(BaseModel):
    """Établissement servi par l'instance : nom et structures racines du périmètre des personnes, titre et teinte de l'application."""

    name: str
    root_structure_ids: list[int]
    title: str | None
    """Titre de l'application. Pour `None`, l'interface compose le titre avec `name`."""
    brand_hue: int
    """Teinte de l'interface, angle OKLCH en degrés."""
