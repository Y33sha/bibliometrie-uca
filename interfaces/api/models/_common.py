"""Modèles Pydantic partagés par plusieurs routers : corps des requêtes entrantes et réponses d'acquittement après mutation."""

from pydantic import BaseModel

# ----- Réponses génériques d'acquittement -----


class DeletedResponse(BaseModel):
    deleted: bool = True


class RemovedResponse(BaseModel):
    removed: bool = True


class OkResponse(BaseModel):
    """Réponse minimale d'acquittement (pas de données)."""

    ok: bool = True


class BatchUpdatedResponse(BaseModel):
    updated: int


class CreatedIdResponse(BaseModel):
    """Réponse générique : `{id: int}` après création."""

    id: int


class StatusResponse(BaseModel):
    """Réponse générique : `{status: str}` (mutations sans corps utile)."""

    status: str


class TotalCountResponse(BaseModel):
    """Compteur générique : `{total: int}` (utilisé par les endpoints `/count`)."""

    total: int


class EnumOption(BaseModel):
    """Une valeur d'enum exposée à l'interface : `{value, label_fr}`.

    Sert aux endpoints qui alimentent les listes déroulantes (publisher_type, journal_type, …). La source de vérité côté Python est l'ordre de la constante associée (ex. `domain.publishers.PUBLISHER_TYPES`).
    """

    value: str
    label_fr: str


# ----- Fusion d'entités (revues, éditeurs, personnes) -----


class MergeRequest(BaseModel):
    """Fusionne l'entité `source_id` dans celle désignée par le chemin."""

    source_id: int


class MergeResponse(BaseModel):
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
    "RemovedResponse",
    "StatusResponse",
    "TotalCountResponse",
]
