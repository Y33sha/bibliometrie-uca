"""Modèles Pydantic transverses : facets, réponses génériques, refs partagées."""

from pydantic import BaseModel

# ----- Facet primitives -----


class FacetValueCount(BaseModel):
    value: str
    count: int


class YesNoCount(BaseModel):
    yes: int
    no: int


# ----- Réponses génériques d'acquittement -----


class DeletedResponse(BaseModel):
    deleted: bool = True


class RemovedResponse(BaseModel):
    removed: bool = True


class OkResponse(BaseModel):
    """Réponse minimale d'acquittement (pas de données)."""

    ok: bool = True


class DetachedResponse(BaseModel):
    detached: bool = True


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


# ----- Merge (journals / publishers / persons) -----


class MergeRequest(BaseModel):
    source_id: int


class MergeResponse(BaseModel):
    merged: bool
    source_id: int
    target_id: int


# ----- Refs partagées entre publications, persons, laboratories -----


class StructureRef(BaseModel):
    """Référence courte à une structure (acronyme + nom)."""

    acronym: str | None
    name: str


class ValueConfirmedOut(BaseModel):
    """Identifiant sous forme condensée (annuaire public)."""

    value: str
    confirmed: bool


# ----- Blocs dashboard partagés (laboratoires + personnes) -----


class PubYearCount(BaseModel):
    year: int
    count: int


class DashboardOa(BaseModel):
    open_access: int
    closed: int
    unknown: int
    total: int
