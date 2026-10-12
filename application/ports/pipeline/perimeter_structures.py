"""Port : lecture des périmètres (ensembles de structures).

Implémenté par `pipeline.structures.perimeter.PerimeterQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PerimeterStructuresQueries(Protocol):
    """Opérations sur les périmètres (lecture des structures, rematérialisation)."""

    def count_extraction_structures(self, conn: Connection) -> int:
        """Nombre de structures du périmètre d'extraction, zéro s'il n'est pas configuré."""
        ...

    def get_persons_structure_ids_list(self, conn: Connection) -> list[int]:
        """Structures du périmètre personnes, en liste — forme attendue d'un paramètre lié `ANY(:ids)`."""
        ...

    def refresh_perimeter_structures(self, conn: Connection) -> None:
        """Recompute la table matérialisée `perimeter_structures` (clôture des tutelles). Idempotent. Commit laissé au caller."""
        ...
