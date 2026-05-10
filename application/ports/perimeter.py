"""Port : lecture des périmètres (ensembles de structures).

Implémenté par `infrastructure.db.queries.perimeter.PgPerimeterQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PerimeterQueries(Protocol):
    """Opérations de lecture sur les périmètres."""

    def get_persons_structure_ids_list(self, cur: Connection) -> list[int]:
        """Liste des structure_ids du périmètre personnes (pour ANY(%s))."""
        ...
