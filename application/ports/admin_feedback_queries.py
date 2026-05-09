"""Port : lectures pour le tableau de bord admin de feedback détection
d'adresses (consommé par /api/admin/feedback/*).

Deux variantes :
- `AsyncAdminFeedbackQueries` : routers async.
- `AdminFeedbackQueries` : routers sync (chantier sync-async-deduplication).
"""

from typing import Any, Protocol


class AsyncAdminFeedbackQueries(Protocol):
    """Lectures async sur le feedback de détection d'adresses."""

    async def feedback_structures(self, types: list[str]) -> list[dict[str, Any]]: ...

    async def feedback_stats(self, structure_id: int) -> dict[str, Any]: ...

    async def feedback_false_negatives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> dict[str, Any]: ...

    async def feedback_false_positives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> dict[str, Any]: ...


class AdminFeedbackQueries(Protocol):
    """Variante sync d'`AsyncAdminFeedbackQueries`."""

    def feedback_structures(self, types: list[str]) -> list[dict[str, Any]]: ...

    def feedback_stats(self, structure_id: int) -> dict[str, Any]: ...

    def feedback_false_negatives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> dict[str, Any]: ...

    def feedback_false_positives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> dict[str, Any]: ...
