"""Types Pydantic transverses retournés par plusieurs ports `application.ports.api.*`.

Vit ici (et pas dans `interfaces/api/models/_common.py`) parce que ces shapes sont des retours de query services partagés entre features (labs + persons + publications). Les ports les importent directement ; `interfaces/api/models/` ne contient que les types router-only (`OkResponse`, `MergeRequest`, etc.).
"""

import math

from pydantic import BaseModel, Field, computed_field


def page_count(total: int, per_page: int) -> int:
    """Nombre de pages couvrant `total` résultats, zéro sur un résultat vide."""
    return math.ceil(total / per_page)


class PaginatedResponse(BaseModel):
    """Socle des lectures paginées : la tranche demandée et de quoi situer le reste.

    `pages` se déduit de `total` et `per_page` — c'est une conséquence, pas une donnée. Les réponses qui en héritent ajoutent leur liste de résultats et ce que leur lecture porte en propre.
    """

    total: int
    page: int
    per_page: int = Field(gt=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pages(self) -> int:
        return page_count(self.total, self.per_page)


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


class PubYearCount(BaseModel):
    year: int
    count: int


class DashboardOa(BaseModel):
    open_access: int
    embargoed: int
    closed: int
    unknown: int
    total: int


__all__ = [
    "DashboardOa",
    "FacetValueCount",
    "PaginatedResponse",
    "PubYearCount",
    "page_count",
    "StructureRef",
    "YesNoCount",
]
