"""Port PerimeterRepository — contrat d'accès à l'agrégat Perimeter.

Implémenté par `infrastructure/repositories/perimeter_repository.py`.
"""

from typing import Annotated, Protocol

from pydantic import BaseModel, StringConstraints

from domain.perimeters.perimeter import Perimeter


class PerimeterUpdate(BaseModel):
    """Champs éditables d'un périmètre, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). `structure_ids` liste les structures **racines** ; la clôture qui en descend est matérialisée à part, et son recalcul revient au caller.
    """

    name: Annotated[str, StringConstraints(strip_whitespace=True)] | None = None
    structure_ids: list[int] | None = None


class PerimeterRepository(Protocol):
    """Contrat d'accès à la table `perimeters`."""

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, perimeter_id: int) -> Perimeter | None:
        """Hydrate l'aggregate `Perimeter` complet (code, name,
        `structure_ids`). Retourne None si le perimeter n'existe pas.
        `structure_ids` reste sous forme d'ids (références par id à
        l'aggregate Structure)."""
        ...

    # ── Liens structure ↔ perimeter ────────────────────────────────

    def add_structure_to_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool: ...

    def remove_structure_from_all_perimeters(self, structure_id: int) -> None:
        """Retire une structure des racines (`structure_ids`) de tout périmètre, après sa suppression."""
        ...

    # ── CRUD ───────────────────────────────────────────────────────

    def perimeter_exists(self, perimeter_id: int) -> bool: ...

    def perimeter_code_exists(self, code: str) -> bool: ...

    def create_perimeter(
        self,
        *,
        code: str,
        name: str,
    ) -> int: ...

    def update_perimeter_fields(self, perimeter_id: int, fields: PerimeterUpdate) -> None: ...

    def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    def delete_perimeter(self, perimeter_id: int) -> None: ...

    # ── Matérialisation ────────────────────────────────────────────

    def refresh_structures(self) -> None:
        """Recompute la table matérialisée `perimeter_structures` (clôture récursive
        `est_tutelle_de` de chaque `perimeters.structure_ids`). À rejouer après toute
        édition des racines d'un périmètre ou d'une relation `structure_relations`."""
        ...
