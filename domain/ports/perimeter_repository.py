"""Ports `PerimeterRepository` / `AsyncPerimeterRepository` — contrat
d'accès à l'agrégat Perimeter.

Implémentés par
- `infrastructure/repositories/perimeter_repository.py` (sync)
- `infrastructure/repositories/async_perimeter_repository.py` (async)
"""

from typing import Protocol


class PerimeterRepository(Protocol):
    """Contrat sync d'accès à la table `perimeters`."""

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
