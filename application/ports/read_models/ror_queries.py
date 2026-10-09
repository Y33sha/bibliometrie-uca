"""Port : lectures du rapport de cohérence entre `structure_tutelles` et le référentiel ROR.

Implémenté par `infrastructure.read_models.ror.PgRorCoherenceQueries`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from domain.structures.identifiers import RorId


@dataclass(frozen=True, slots=True)
class StructureRor:
    id: int
    code: str
    ror_id: RorId | None


class RorCoherenceQueries(Protocol):
    def structures(self) -> list[StructureRor]: ...

    def tutelles(self) -> list[tuple[int, int]]:
        """Couples `(parent, enfant)` de `structure_tutelles`."""
        ...

    def perimeter_structure_ids(self) -> frozenset[int]:
        """Structures d'au moins un périmètre."""
        ...

    def ror_relations(self) -> list[tuple[RorId, RorId]]:
        """Couples `(parent, enfant)` de `ror_relations`."""
        ...

    def ror_names(self, ror_ids: Iterable[RorId]) -> dict[RorId, str]: ...
