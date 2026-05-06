"""Port : lectures pour le tableau de bord admin de feedback détection
d'adresses (consommé par /api/admin/feedback/*).

Implémenté par
`infrastructure.db.queries.admin_feedback.PgAsyncAdminFeedbackQueries`.
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
