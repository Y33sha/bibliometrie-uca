"""Port : lectures sur les périmètres pour le router /api/perimeters/.

Implémenté par `infrastructure.queries.perimeter.PgPerimetersQueries`.
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


class PerimetersQueries(Protocol):
    """Lectures pour /api/perimeters."""

    def list_perimeters_with_structures(self) -> list[PerimeterOut]: ...
