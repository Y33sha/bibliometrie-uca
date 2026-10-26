"""Modèles de réponse : résolution du libellé d'une entité de facette."""

from pydantic import BaseModel


class EntityLabelResponse(BaseModel):
    """Libellé d'une entité résolu par id (None si l'id est inconnu). Réaffiche une pastille de facette restaurée depuis l'URL, où seul l'id est transporté."""

    label: str | None
