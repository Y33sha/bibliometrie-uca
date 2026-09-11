"""Port : lectures sur les périmètres et l'établissement servi par l'instance.

Implémenté par `infrastructure.read_models.perimeters.PgPerimetersQueries`.
"""

from typing import Protocol

from pydantic import BaseModel


class PerimeterStructureItem(BaseModel):
    id: int
    name: str
    acronym: str | None
    code: str


class PerimeterOut(BaseModel):
    """Un périmètre : ses structures racines (`root_structure_ids` bruts, `structures` résolues) et `structure_count`, la taille de la clôture transitive de ces racines (avec leurs sous-structures) — donc distinct du nombre de racines."""

    id: int
    code: str
    name: str
    root_structure_ids: list[int]
    structures: list[PerimeterStructureItem]
    structure_count: int


class InstitutionOut(BaseModel):
    """Établissement servi par l'instance : nom et structures racines du périmètre des personnes."""

    name: str
    root_structure_ids: list[int]


class PerimetersQueries(Protocol):
    """Lectures sur les périmètres et l'établissement servi par l'instance."""

    def list_perimeters_with_structures(self) -> list[PerimeterOut]: ...

    def institution(self) -> InstitutionOut: ...
