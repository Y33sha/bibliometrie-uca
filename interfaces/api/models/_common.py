"""Modèles Pydantic partagés par plusieurs routers : corps des requêtes entrantes et réponses d'acquittement après mutation."""

from application.ports.model import Model

# ----- Réponses génériques d'acquittement -----


class DeletedResponse(Model):
    """Acquittement de suppression : `{deleted: true}`."""

    deleted: bool = True


class OkResponse(Model):
    """Acquittement sans données."""

    ok: bool = True


class BatchUpdatedResponse(Model):
    """Décompte d'une mise à jour en lot : `{updated: int}`."""

    updated: int


class CreatedIdResponse(Model):
    """Réponse générique : `{id: int}` après création."""

    id: int


class TotalCountResponse(Model):
    """Compteur générique : `{total: int}` (routes `/count`)."""

    total: int


class EnumOption(Model):
    """Valeur d'enum pour les listes déroulantes de l'interface (publisher_type, serial_type…) : `{value, label_fr}`. L'ordre vient de la constante du domaine (`domain.publishers.PUBLISHER_TYPES`, par exemple)."""

    value: str
    label_fr: str


# ----- Fusion d'entités (revues, éditeurs, personnes) -----


class MergeRequest(Model):
    """Demande de fusion de l'entité `source_id` dans celle désignée par le chemin."""

    source_id: int


class MergeResponse(Model):
    """Acquittement de fusion : l'entité absorbée (`source_id`) et la survivante (`target_id`)."""

    merged: bool
    source_id: int
    target_id: int


__all__ = [
    "BatchUpdatedResponse",
    "CreatedIdResponse",
    "DeletedResponse",
    "EnumOption",
    "MergeRequest",
    "MergeResponse",
    "OkResponse",
    "TotalCountResponse",
]
