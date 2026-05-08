"""Port : lectures sur les sujets (consommé par le router subjects).

Deux variantes :
- `AsyncSubjectsQueries` : pour les routers FastAPI async (en cours
  de migration vers sync — chantier sync-async-deduplication).
- `SubjectsAdminQueries` : pour les routers FastAPI sync (option D
  du chantier).

Implémentés respectivement par
`infrastructure.db.queries.subjects.PgAsyncSubjectsQueries` et
`infrastructure.db.queries.subjects.PgSubjectsAdminQueries`.

Note : `application.ports.subjects.SubjectsQueries` couvre la variante
sync utilisée par le pipeline de normalisation (upsert/link/cleanup).
Ce port-ci ne couvre que les lectures de l'API admin.
"""

from typing import Any, Protocol


class AsyncSubjectsQueries(Protocol):
    """Lectures async sur les sujets (annuaire, voisins par co-occurrence)."""

    async def list_subjects(
        self, *, q: str | None, limit: int, offset: int, min_count: int
    ) -> list[dict[str, Any]]: ...

    async def count_subjects(self, *, q: str | None, min_count: int) -> int: ...

    async def get_subject(self, subject_id: int) -> dict[str, Any] | None: ...

    async def get_subject_neighbors(
        self, subject_id: int, *, limit: int, min_count: int
    ) -> list[dict[str, Any]]: ...


class SubjectsAdminQueries(Protocol):
    """Variante sync d'`AsyncSubjectsQueries` pour les routers `def`."""

    def list_subjects(
        self, *, q: str | None, limit: int, offset: int, min_count: int
    ) -> list[dict[str, Any]]: ...

    def count_subjects(self, *, q: str | None, min_count: int) -> int: ...

    def get_subject(self, subject_id: int) -> dict[str, Any] | None: ...

    def get_subject_neighbors(
        self, subject_id: int, *, limit: int, min_count: int
    ) -> list[dict[str, Any]]: ...
