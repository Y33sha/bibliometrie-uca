"""Port PerimeterRepository — contrat d'accès à l'agrégat Perimeter.

Implémenté par `infrastructure/repositories/perimeter_repository.py`.
"""

from typing import Protocol, TypedDict

from domain.perimeters.perimeter import Perimeter


class PerimeterUpdateFields(TypedDict, total=False):
    """Partial update sur la table `perimeters` (clés optionnelles)."""

    name: str
    structure_ids: list[int]


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

    def remove_structure_from_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool: ...

    # ── CRUD ───────────────────────────────────────────────────────

    def perimeter_exists(self, perimeter_id: int) -> bool: ...

    def perimeter_code_exists(self, code: str) -> bool: ...

    def create_perimeter(
        self,
        *,
        code: str,
        name: str,
    ) -> int: ...

    def update_perimeter_fields(self, perimeter_id: int, fields: PerimeterUpdateFields) -> None: ...

    def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    def delete_perimeter(self, perimeter_id: int) -> None: ...

    # ── Matérialisation ────────────────────────────────────────────

    def refresh_structures(self) -> None:
        """Recompute la table matérialisée `perimeter_structures` (clôture récursive
        `est_tutelle_de` de chaque `perimeters.structure_ids`). À rejouer après toute
        édition des racines d'un périmètre ou d'une relation `structure_relations`."""
        ...
