"""Modèles Pydantic propres au routeur des revues.

Le contrat d'édition `SerialUpdate` est déclaré dans le port `application/ports/repositories/serial_repository.py` ; les modèles de réponse des lectures dans `infrastructure/read_models/serials/models.py`.
"""

from application.ports.model import Model
from domain.serials.serial import SerialType


class SerialTypeChange(Model):
    """Type de revue prévu, soumis par la fenêtre d'édition pour connaître son effet avant confirmation."""

    serial_type: SerialType


class SerialTypeChangeImpact(Model):
    """Effet du type de revue prévu : nombre de publications à changer de type."""

    count: int
