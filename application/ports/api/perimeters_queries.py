"""Port : lectures sur les périmètres pour le router /api/perimeters/.

Distinct de `application.ports.pipeline.perimeter.PerimeterQueries`, qui expose au pipeline la résolution du périmètre `persons` : ce port-ci sert le listing complet des périmètres.

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
    """Périmètre + ses structures racines (résolues + comptage effectif)."""

    id: int
    code: str
    name: str
    structure_ids: list[int]
    structures: list[PerimeterStructureItem]
    structure_count: int


class PerimetersQueries(Protocol):
    """Lectures pour /api/perimeters."""

    def list_perimeters_with_structures(self) -> list[PerimeterOut]: ...
