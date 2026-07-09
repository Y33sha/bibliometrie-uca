"""Port : lecture des périmètres (ensembles de structures).

Implémenté par `infrastructure.queries.perimeter.PgPerimeterQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PerimeterQueries(Protocol):
    """Opérations sur les périmètres (lecture des structures, rematérialisation)."""

    def get_persons_structure_ids_list(self, conn: Connection) -> list[int]:
        """Liste des structure_ids du périmètre personnes (pour ANY(%s))."""
        ...

    def refresh_perimeter_structures(self, conn: Connection) -> int:
        """Recompute la table matérialisée `perimeter_structures` (clôture des tutelles).

        Idempotent, retourne le nombre de liens. Commit laissé au caller.
        """
        ...
