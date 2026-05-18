"""Modèles Pydantic (router-only) pour la page admin feedback.

Les DTOs retournés par le port `AdminFeedbackQueries` (FeedbackStats, FeedbackAddressesResponse, FeedbackStructureItem, et les sous-types FeedbackLabDetected/FeedbackMatchedForm/FeedbackAddressItem) vivent dans `application/ports/api/admin_feedback_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Reste ici la réponse composée par le router (groupement par type + structure par défaut).
"""

from pydantic import BaseModel

from application.ports.api.admin_feedback_queries import FeedbackStructureItem


class FeedbackStructuresResponse(BaseModel):
    """Structures éligibles au tableau de bord feedback, groupées par type, avec la structure à sélectionner par défaut (UCA si présente)."""

    by_type: dict[str, list[FeedbackStructureItem]]
    default_structure_id: int | None
