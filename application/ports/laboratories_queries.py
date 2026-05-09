"""Port : lectures sur les laboratoires (consommé par le router laboratories).

Deux variantes (chantier sync-async-deduplication, option D) :
- `AsyncLaboratoriesQueries` : routers async.
- `LaboratoriesQueries` : routers sync.

Implémentés respectivement par `PgAsyncLaboratoriesQueries` et
`PgLaboratoriesQueries` dans `infrastructure.db.queries.laboratories`.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class LabPersonsFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_rh: str = ""
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""


class AsyncLaboratoriesQueries(Protocol):
    """Lectures async sur les laboratoires."""

    async def list_laboratories(self) -> list[dict[str, Any]]: ...

    async def get_laboratory(self, lab_id: int) -> dict[str, Any] | None: ...

    async def get_laboratory_persons(
        self,
        lab_id: int,
        *,
        filters: LabPersonsFilters,
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]: ...

    async def get_laboratory_addresses(
        self, lab_id: int, *, page: int, per_page: int
    ) -> dict[str, Any]: ...

    async def get_laboratory_subjects(self, lab_id: int, *, limit: int) -> list[dict[str, Any]]: ...

    async def get_laboratory_dashboard(self, lab_id: int) -> dict[str, Any]: ...


class LaboratoriesQueries(Protocol):
    """Variante sync d'`AsyncLaboratoriesQueries`."""

    def list_laboratories(self) -> list[dict[str, Any]]: ...

    def get_laboratory(self, lab_id: int) -> dict[str, Any] | None: ...

    def get_laboratory_persons(
        self,
        lab_id: int,
        *,
        filters: LabPersonsFilters,
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]: ...

    def get_laboratory_addresses(
        self, lab_id: int, *, page: int, per_page: int
    ) -> dict[str, Any]: ...

    def get_laboratory_subjects(self, lab_id: int, *, limit: int) -> list[dict[str, Any]]: ...

    def get_laboratory_dashboard(self, lab_id: int) -> dict[str, Any]: ...
