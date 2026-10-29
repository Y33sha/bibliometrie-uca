"""Modèles Pydantic propres au routeur des revues.

Le contrat d'édition `SerialUpdate` vit dans le port `application/ports/repositories/serial_repository.py` ; les modèles de réponse des lectures dans `infrastructure/read_models/serials/models.py`.
"""

from pydantic import BaseModel

from domain.serials.serial import SerialType


class SerialTypeChange(BaseModel):
    """Type de revue dont la fenêtre d'édition de l'administration demande l'effet avant de confirmer."""

    serial_type: SerialType


class SerialTypeChangeImpact(BaseModel):
    """Nombre de publications dont le type changerait avec le type de revue prévu, rendu avant la confirmation de l'édition."""

    count: int
