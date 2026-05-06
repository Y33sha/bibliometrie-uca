"""Port : lectures sur les sujets (consommé par le router subjects).

Implémenté par `infrastructure.db.queries.subjects.PgAsyncSubjectsQueries`.

Note : `application.ports.subjects.SubjectsQueries` couvre la variante
sync utilisée par le pipeline de normalisation (upsert/link/cleanup).
Ce port-ci ne couvre que les lectures asynchrones de l'API.
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
