"""Modèles Pydantic propres au routeur des revues.

Le contrat d'édition `SerialUpdate` vit dans le port `application/ports/repositories/serial_repository.py` ; les modèles de réponse des lectures dans `infrastructure/read_models/serials/models.py`.
"""

from pydantic import BaseModel

from domain.serials.serial import SerialType


class SerialTypeChange(BaseModel):
    """Valeur de `serial_type` dont la modale admin demande l'impact avant de confirmer l'édition."""

    serial_type: SerialType


class SerialTypeChangeImpact(BaseModel):
    """Compte des publications dont le `doc_type` canonique changerait si le `serial_type` passait à la valeur prévue. Renvoyé par le preview de la modale admin avant confirmation de l'édition."""

    count: int
