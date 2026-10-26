"""Types Pydantic transverses retournés par plusieurs ports `application.ports.read_models.*`."""

import math
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from domain.sources.registry import Source, source_record_url


def page_count(total: int, per_page: int) -> int:
    """Nombre de pages couvrant `total` résultats, zéro sur un résultat vide."""
    return math.ceil(total / per_page)


class PaginatedResponse(BaseModel):
    """Socle des lectures paginées : la tranche demandée et de quoi situer le reste.

    `pages` se déduit de `total` et `per_page` — c'est une conséquence, pas une donnée. Les réponses qui en héritent ajoutent leur liste de résultats et les champs propres à leur lecture.
    """

    total: int
    page: int
    per_page: int = Field(gt=0)

    @computed_field
    @property
    def pages(self) -> int:
        return page_count(self.total, self.per_page)


class SourceLink(BaseModel):
    """Identifiant d'un enregistrement source et son lien vers le portail de la source."""

    source_id: str
    record_url: str


def hal_links(halids: list[str] | None) -> list[SourceLink]:
    """Liens des dépôts HAL `halids`."""
    return [
        SourceLink(source_id=h, record_url=source_record_url(Source.HAL, h)) for h in halids or []
    ]


class FacetOption(BaseModel):
    """Option d'une facette de liste : la valeur filtrable, son libellé d'affichage, le décompte.

    `label` vaut `None` quand la valeur s'affiche telle quelle (année, statut) ou que le libellé est résolu côté client ; il contient le texte présentable quand seule la requête le connaît (nom de laboratoire, intitulé traduit).
    """

    value: str
    label: str | None = None
    count: int


EntityKind = Literal["publisher", "serial", "person", "subject", "partner"]


class EntityFacetItem(BaseModel):
    id: int | str
    """Identifiant de l'entité : un entier, ou un ROR pour une organisation partenaire."""
    label: str
    count: int


class EntityFacetResponse(BaseModel):
    """Facette d'entité à forte cardinalité (éditeur, revue, auteur, sujet).

    Les options sont calculées côté serveur sous les filtres actifs du contexte (tableau de bord ou liste de publications), d'où des décomptes contextuels et une corrélation entre entités (une revue sélectionnée restreint les éditeurs proposés). La recherche par nom borne la requête.
    """

    entities: list[EntityFacetItem]


class YesNoCount(BaseModel):
    yes: int
    no: int


class StructureRef(BaseModel):
    """Référence courte à une structure (acronyme + nom)."""

    acronym: str | None
    name: str


class PublicationYearCount(BaseModel):
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
    "EntityFacetItem",
    "EntityFacetResponse",
    "EntityKind",
    "FacetOption",
    "PaginatedResponse",
    "PublicationYearCount",
    "page_count",
    "StructureRef",
    "YesNoCount",
]
