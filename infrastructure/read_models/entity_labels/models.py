"""Modèles de réponse : résolution du libellé d'une entité de facette."""

from pydantic import BaseModel


class EntityLabelResponse(BaseModel):
    """Libellé d'une entité, ou `None` si l'id est inconnu."""

    label: str | None
