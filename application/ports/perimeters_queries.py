"""Port : lectures sur les périmètres pour le router /api/perimeters/.

Distinct de `application.ports.perimeter.AsyncPerimeterQueries` qui
expose la résolution du périmètre `persons` consommée par d'autres
modules. Ce port-ci sert le listing complet pour la page admin
périmètres.

Implémenté par
`infrastructure.db.queries.perimeter.PgAsyncPerimetersAdminQueries`.
"""

from typing import Any, Protocol


class AsyncPerimetersAdminQueries(Protocol):
    """Lectures pour /api/perimeters (admin)."""

    async def list_perimeters_with_structures(self) -> list[dict[str, Any]]: ...
