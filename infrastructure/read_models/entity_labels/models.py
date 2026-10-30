"""Modèles de réponse : résolution du libellé d'une entité de facette."""

from application.ports.model import Model


class EntityLabelResponse(Model):
    """Libellé d'une entité, ou `None` si l'id est inconnu."""

    label: str | None
