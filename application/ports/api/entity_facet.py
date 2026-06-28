"""DTO partagé : facette d'entité à forte cardinalité (éditeur, revue).

Les options sont calculées côté serveur sous les filtres actifs du contexte (tableau de bord ou
liste de publications), d'où des décomptes contextuels et une corrélation entre entités (une revue
sélectionnée restreint les éditeurs proposés). La recherche par nom borne la requête.
"""

from pydantic import BaseModel


class EntityFacetItem(BaseModel):
    id: int
    label: str
    count: int


class EntityFacetResponse(BaseModel):
    entities: list[EntityFacetItem]


class EntityLabelResponse(BaseModel):
    """Libellé d'une entité résolu par id (None si l'id est inconnu). Réaffiche une pastille de
    facette restaurée depuis l'URL, où seul l'id — l'état canonique — est transporté."""

    label: str | None
