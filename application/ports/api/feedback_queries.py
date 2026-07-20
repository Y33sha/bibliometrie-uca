"""Port : lectures du tableau de bord de qualité de la détection d'adresses (consommé par /api/feedback/*).

Implémenté par `infrastructure.queries.api.feedback.PgFeedbackQueries`.
"""

from typing import Protocol

from pydantic import BaseModel

from application.ports.api._common import PaginatedResponse
from application.ports.api.addresses_queries import AddressStructureSummary


class FeedbackStats(BaseModel):
    """GET /api/feedback/stats : qualité de la détection d'adresses."""

    total_reviewed: int
    detection_rate: float | None
    false_negatives: int
    false_positives: int
    concordant_valid: int
    pending: int


class FeedbackMatchedForm(BaseModel):
    """Forme de nom ayant matché lors de la détection (faux positif)."""

    form_id: int
    form_text: str
    structure_name: str
    requires_context_of: list[int] | None


class FeedbackAddressItem(BaseModel):
    """Ligne d'adresse dans false-negatives / false-positives.

    `matched_forms` n'est rempli que pour les faux positifs.
    """

    id: int
    raw_text: str
    pub_count: int
    structures: list[AddressStructureSummary]
    matched_forms: list[FeedbackMatchedForm] | None = None


class FeedbackAddressesResponse(PaginatedResponse):
    addresses: list[FeedbackAddressItem]


class FeedbackQueries(Protocol):
    """Lectures sur le feedback de détection d'adresses."""

    def feedback_stats(self, structure_id: int) -> FeedbackStats: ...

    def feedback_false_negatives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> FeedbackAddressesResponse: ...

    def feedback_false_positives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> FeedbackAddressesResponse: ...
