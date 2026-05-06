"""Port AsyncPerimeterRepository — contrat d'accès à l'agrégat Perimeter.

Implémenté par infrastructure/repositories/async_perimeter_repository.py.
"""

from typing import Protocol


class AsyncPerimeterRepository(Protocol):
    """Contrat async d'accès à la table `perimeters`."""

    # ── Liens structure ↔ perimeter ────────────────────────────────

    async def add_structure_to_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool: ...

    async def remove_structure_from_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool: ...

    # ── CRUD ───────────────────────────────────────────────────────

    async def perimeter_exists(self, perimeter_id: int) -> bool: ...

    async def perimeter_code_exists(self, code: str) -> bool: ...

    async def create_perimeter(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
    ) -> int: ...

    async def update_perimeter_fields(self, perimeter_id: int, fields: dict) -> None: ...

    async def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    async def delete_perimeter(self, perimeter_id: int) -> None: ...
