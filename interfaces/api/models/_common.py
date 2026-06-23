"""Modèles Pydantic transverses router-side : réponses génériques + bodies.

Les types **retournés par les ports** (facets, refs de structure, blocs
dashboard partagés) vivent dans `application/ports/api/_common.py` et
sont re-exportés ici pour compat des importeurs historiques. Les types
**router-only** (réponses d'acquittement après mutation, bodies HTTP)
sont définis ici.
"""

from pydantic import BaseModel

from application.ports.api._common import (
    DashboardOa,
    FacetValueCount,
    PubYearCount,
    StructureRef,
    ValueConfirmedOut,
    YesNoCount,
)

# ----- Réponses génériques d'acquittement (router-only) -----


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
    """Une valeur d'enum exposée à l'UI : `{value, label_fr}`.

    Sert aux endpoints qui alimentent les dropdowns (publisher_type,
    journal_type, …). La source de vérité côté Python est l'ordre de
    la constante associée (ex. `domain.publishers.PUBLISHER_TYPES`).
    """

    value: str
    label_fr: str


# ----- Merge (journals / publishers / persons) -----


class MergeRequest(BaseModel):
    source_id: int


class MergeResponse(BaseModel):
    merged: bool
    source_id: int
    target_id: int


__all__ = [
    "BatchUpdatedResponse",
    "CreatedIdResponse",
    "DashboardOa",
    "DeletedResponse",
    "EnumOption",
    "FacetValueCount",
    "MergeRequest",
    "MergeResponse",
    "OkResponse",
    "PubYearCount",
    "RemovedResponse",
    "StatusResponse",
    "StructureRef",
    "TotalCountResponse",
    "ValueConfirmedOut",
    "YesNoCount",
]
