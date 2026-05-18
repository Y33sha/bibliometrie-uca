"""Port : lectures sur les périmètres pour le router /api/perimeters/.

Distinct de `application.ports.perimeter.PerimeterQueries` qui expose
la résolution du périmètre `persons` consommée par d'autres modules.
Ce port-ci sert le listing complet pour la page admin périmètres.

Implémenté par
`infrastructure.queries.perimeter.PgPerimetersAdminQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4 — les DTOs vivent dans le port qui les définit (zone neutre, à côté des Protocols).
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
    description: str | None
    structure_ids: list[int]
    structures: list[PerimeterStructureItem]
    structure_count: int


class PerimetersAdminQueries(Protocol):
    """Lectures pour /api/perimeters (admin)."""

    def list_perimeters_with_structures(self) -> list[PerimeterOut]: ...
