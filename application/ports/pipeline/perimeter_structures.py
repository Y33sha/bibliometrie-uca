"""Port : structures des périmètres, matérialisées dans `perimeter_structures`.

Implémenté par `pipeline.transformation.structures.perimeter.PerimeterStructures`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PerimeterStructures(Protocol):
    """Clôture des tutelles des périmètres : rematérialisation et lecture."""

    def refresh(self, conn: Connection) -> None:
        """Recompute la table matérialisée `perimeter_structures` (clôture des tutelles). Idempotent. Commit laissé au caller."""
        ...

    def persons_structure_ids(self, conn: Connection) -> list[int]:
        """Structures du périmètre personnes, en liste — forme attendue d'un paramètre lié `ANY(:ids)`."""
        ...
