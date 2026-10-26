"""Port : structures des périmètres, matérialisées dans `perimeter_structures`.

Implémenté par `pipeline.transformation.structures.perimeter.PerimeterStructures`.
"""

from typing import Protocol


class PerimeterStructures(Protocol):
    """Clôture des tutelles des périmètres : rematérialisation et lecture."""

    def refresh(self) -> None:
        """Recompute la table matérialisée `perimeter_structures` (clôture des tutelles). Idempotent. Commit laissé au caller."""
        ...

    def persons_structure_ids(self) -> list[int]:
        """Structures du périmètre personnes, en liste — forme attendue d'un paramètre lié `ANY(:ids)`."""
        ...
