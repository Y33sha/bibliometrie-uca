"""Types Pydantic transverses retournés par plusieurs ports `application.ports.api.*`.

Vit ici (et pas dans `interfaces/api/models/_common.py`) parce que ces shapes
sont des retours de query services partagés entre features (labs + persons +
publications). Les ports les importent directement ; `interfaces/api/models/`
ne contient que les types router-only (`OkResponse`, `MergeRequest`, etc.).
"""

from pydantic import BaseModel


class FacetValueCount(BaseModel):
    value: str
    count: int


class YesNoCount(BaseModel):
    yes: int
    no: int


class StructureRef(BaseModel):
    """Référence courte à une structure (acronyme + nom)."""

    acronym: str | None
    name: str


class ValueConfirmedOut(BaseModel):
    """Identifiant sous forme condensée (annuaire public)."""

    value: str
    confirmed: bool


class PubYearCount(BaseModel):
    year: int
    count: int


class DashboardOa(BaseModel):
    open_access: int
    closed: int
    unknown: int
    total: int


__all__ = [
    "DashboardOa",
    "FacetValueCount",
    "PubYearCount",
    "StructureRef",
    "ValueConfirmedOut",
    "YesNoCount",
]
