"""Adapter PostgreSQL pour `application.ports.perimeter.PerimeterQueries`.

Thin wrapper autour des fonctions de `infrastructure.perimeter` pour les
exposer en tant que port à la couche application. Variantes sync
(pipeline) et async (API, §2.12) côte à côte.
"""

from typing import Any

from infrastructure.perimeter import (
    async_get_persons_structure_ids_list,
    get_persons_structure_ids_list,
)


class PgPerimeterQueries:
    """Adapter PostgreSQL pour `application.ports.perimeter.PerimeterQueries`."""

    def get_persons_structure_ids_list(self, cur: Any) -> list[int]:
        return get_persons_structure_ids_list(cur)


class PgAsyncPerimeterQueries:
    """Variante async — adapter pour `AsyncPerimeterQueries` (§2.12)."""

    async def get_persons_structure_ids_list(self, cur: Any) -> list[int]:
        return await async_get_persons_structure_ids_list(cur)
