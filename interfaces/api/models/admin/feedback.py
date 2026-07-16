"""Modèles Pydantic du router de la page de retours : réponse composée par le router."""

from pydantic import BaseModel

from application.ports.api.admin_feedback_queries import FeedbackStructureItem


class FeedbackStructuresResponse(BaseModel):
    """Structures éligibles au tableau de bord feedback, groupées par type, avec la structure à sélectionner par défaut (UCA si présente)."""

    by_type: dict[str, list[FeedbackStructureItem]]
    default_structure_id: int | None
