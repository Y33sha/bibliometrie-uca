"""Port : lectures sur les périmètres pour le router /api/perimeters/.

Distinct de `application.ports.perimeter.PerimeterQueries` qui expose
la résolution du périmètre `persons` consommée par d'autres modules.
Ce port-ci sert le listing complet pour la page admin périmètres.

Implémenté par
`infrastructure.queries.perimeter.PgPerimetersAdminQueries`.
"""

from typing import Any, Protocol


class PerimetersAdminQueries(Protocol):
    """Lectures pour /api/perimeters (admin)."""

    def list_perimeters_with_structures(self) -> list[dict[str, Any]]: ...
