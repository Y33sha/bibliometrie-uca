"""Port AsyncConfigRepository — contrat d'accès aux agrégats Config et Perimeter.

Implémenté par infrastructure/repositories/async_config_repository.py.
"""

from typing import Any, Protocol


class AsyncConfigRepository(Protocol):
    """Contrat async d'accès aux tables config et perimeters."""

    # ── config (clé / valeur JSON) ─────────────────────────────────

    async def config_key_exists(self, key: str) -> bool: ...

    async def update_config_value(self, key: str, value: Any) -> dict: ...

    async def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]: ...

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

    # ── Perimeter CRUD ─────────────────────────────────────────────

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
