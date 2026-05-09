"""Port PerimeterRepository — contrat d'accès à l'agrégat Perimeter.

Implémenté par `infrastructure/repositories/perimeter_repository.py`.
"""

from typing import Protocol


class PerimeterRepository(Protocol):
    """Contrat d'accès à la table `perimeters`."""

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
        description: str | None,
    ) -> int: ...

    def update_perimeter_fields(self, perimeter_id: int, fields: dict) -> None: ...

    def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    def delete_perimeter(self, perimeter_id: int) -> None: ...
