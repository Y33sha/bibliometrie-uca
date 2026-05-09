"""Port : lectures sur les structures (consommé par le router structures).

Deux variantes :
- `AsyncStructuresQueries` : routers async.
- `StructuresQueries` : routers sync (chantier sync-async-deduplication).
"""

from typing import Any, Protocol


class AsyncStructuresQueries(Protocol):
    """Lectures async sur les structures, relations et formes de noms."""

    async def list_structures(
        self, *, type_filter: str | None, search: str
    ) -> list[dict[str, Any]]: ...

    async def get_structure_detail(self, structure_id: int) -> dict[str, Any] | None: ...

    async def get_name_form(self, form_id: int) -> dict[str, Any] | None: ...


class StructuresQueries(Protocol):
    """Variante sync d'`AsyncStructuresQueries`."""

    def list_structures(self, *, type_filter: str | None, search: str) -> list[dict[str, Any]]: ...

    def get_structure_detail(self, structure_id: int) -> dict[str, Any] | None: ...

    def get_name_form(self, form_id: int) -> dict[str, Any] | None: ...
