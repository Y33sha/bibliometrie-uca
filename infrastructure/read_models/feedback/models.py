"""Modèles de réponse : lectures du tableau de bord de qualité de la détection d'adresses."""

from pydantic import BaseModel

from infrastructure.read_models._common import PaginatedResponse, StructureRef
from infrastructure.read_models.addresses.models import AddressStructureSummary


class FeedbackStats(BaseModel):
    """GET /api/feedback/stats : qualité de la détection d'adresses."""

    total_reviewed: int
    detection_rate: float | None
    false_negatives: int
    false_positives: int
    concordant_valid: int
    pending: int


class FeedbackMatchedForm(BaseModel):
    """Forme de nom reconnue par la détection, dans un faux positif."""

    form_id: int
    form_text: str
    structure: StructureRef
    """Structure de la forme ; l'affichage choisit entre acronyme et nom."""
    requires_context_of: list[int] | None


class FeedbackAddressItem(BaseModel):
    """Adresse d'une liste de faux négatifs ou de faux positifs."""

    id: int
    raw_text: str
    publication_count: int
    structures: list[AddressStructureSummary]
    matched_forms: list[FeedbackMatchedForm] | None = None
    """Rempli seulement pour les faux positifs."""


class FeedbackAddressesResponse(PaginatedResponse):
    addresses: list[FeedbackAddressItem]
