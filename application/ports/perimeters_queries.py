"""Port : lectures sur les périmètres pour le router /api/perimeters/.

Distinct de `application.ports.perimeter.AsyncPerimeterQueries` qui
expose la résolution du périmètre `persons` consommée par d'autres
modules. Ce port-ci sert le listing complet pour la page admin
périmètres.

Deux variantes :
- `AsyncPerimetersAdminQueries` : routers async.
- `PerimetersAdminQueries` : routers sync (chantier sync-async-deduplication).
"""

from typing import Any, Protocol


class AsyncPerimetersAdminQueries(Protocol):
    """Lectures async pour /api/perimeters (admin)."""

    async def list_perimeters_with_structures(self) -> list[dict[str, Any]]: ...


class PerimetersAdminQueries(Protocol):
    """Variante sync d'`AsyncPerimetersAdminQueries`."""

    def list_perimeters_with_structures(self) -> list[dict[str, Any]]: ...
