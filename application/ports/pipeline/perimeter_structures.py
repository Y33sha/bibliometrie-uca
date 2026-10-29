"""Port : structures des périmètres, matérialisées dans `perimeter_structures`.

Implémenté par `pipeline.transformation.structures.perimeter.PerimeterStructures`.
"""

from typing import Protocol


class PerimeterStructures(Protocol):
    """Structures des périmètres : recalcul et lecture."""

    def refresh(self) -> None:
        """Recalcule `perimeter_structures`. L'appelant commite."""
        ...

    def persons_structure_ids(self) -> list[int]:
        """Structures du périmètre des personnes, en liste, la forme qu'attend `ANY(:ids)`."""
        ...
