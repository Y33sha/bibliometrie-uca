"""Adapter PostgreSQL pour `application.ports.perimeter.PerimeterQueries`.

Thin wrapper autour des fonctions de `infrastructure.perimeter` pour les
exposer en tant que port à la couche application.
"""

from typing import Any

from infrastructure.perimeter import get_persons_structure_ids_list


class PgPerimeterQueries:
    """Adapter PostgreSQL pour `application.ports.perimeter.PerimeterQueries`."""

    def get_persons_structure_ids_list(self, cur: Any) -> list[int]:
        return get_persons_structure_ids_list(cur)
