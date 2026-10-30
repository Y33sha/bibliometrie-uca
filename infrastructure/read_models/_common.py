"""Modèles de réponse communs à plusieurs lectures."""

import math
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from domain.sources.registry import Source, source_record_url


def page_count(total: int, per_page: int) -> int:
    """Renvoie le nombre de pages couvrant `total` résultats, zéro sur un résultat vide."""
    return math.ceil(total / per_page)


class PaginatedResponse(BaseModel):
    """Base des lectures paginées : la tranche demandée et sa position dans l'ensemble.

    `pages` se déduit de `total` et `per_page`. Les réponses héritées ajoutent leur liste de résultats et leurs champs propres.
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
    """Renvoie les liens des dépôts HAL donnés."""
    return [
        SourceLink(source_id=h, record_url=source_record_url(Source.HAL, h)) for h in halids or []
    ]


class FacetOption(BaseModel):
    """Option d'une facette de liste : la valeur filtrable, son libellé d'affichage, le décompte."""

    value: str
    label: str | None = None
    """Texte affiché, quand seule la requête le connaît (nom de laboratoire, intitulé traduit). `None` pour une valeur affichée telle quelle (année, statut) ou un libellé résolu côté client."""
    count: int


EntityKind = Literal["publisher", "serial", "person", "subject", "partner"]


class EntityFacetItem(BaseModel):
    id: int | str
    """Identifiant de l'entité : un entier, ou un ROR pour une organisation partenaire."""
    label: str
    count: int


class EntityFacetResponse(BaseModel):
    """Facette d'entité à forte cardinalité (éditeur, revue, auteur, sujet).

    Les options sont calculées côté serveur sous les filtres actifs du contexte (tableau de bord ou liste de publications). Les décomptes dépendent donc du contexte, et les entités se restreignent mutuellement : une revue sélectionnée restreint les éditeurs proposés. La recherche par nom borne la requête.
    """

    entities: list[EntityFacetItem]


class YesNoCount(BaseModel):
    yes: int
    no: int


class StructureRef(BaseModel):
    """Référence courte à une structure (acronyme + nom)."""

    acronym: str | None
    name: str


__all__ = [
    "EntityFacetItem",
    "EntityFacetResponse",
    "EntityKind",
    "FacetOption",
    "PaginatedResponse",
    "page_count",
    "StructureRef",
    "YesNoCount",
]
