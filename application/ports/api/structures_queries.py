"""Port : lectures sur les structures (consommé par le router structures).

Implémenté par `infrastructure.db.queries.structures.PgStructuresQueries`.
"""

from typing import Any, Protocol


class StructuresQueries(Protocol):
    """Lectures sur les structures, relations et formes de noms."""

    def list_structures(self, *, type_filter: str | None, search: str) -> list[dict[str, Any]]: ...

    def get_structure_detail(self, structure_id: int) -> dict[str, Any] | None: ...

    def get_name_form(self, form_id: int) -> dict[str, Any] | None: ...
