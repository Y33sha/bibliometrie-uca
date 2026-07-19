"""Router du libellé d'une entité de facette, servi par le port `EntityLabelQueries`. Sert `/api/entity-labels`."""

from fastapi import APIRouter, Depends, Query

from application.ports.api.entity_facet import (
    EntityKind,
    EntityLabelQueries,
    EntityLabelResponse,
)
from interfaces.api.deps import entity_label_queries

router = APIRouter(prefix="/api/entity-labels", tags=["entity-labels"])


@router.get("", response_model=EntityLabelResponse)
def resolve_entity_label(
    kind: EntityKind = Query(...),
    entity_id: int = Query(...),
    queries: EntityLabelQueries = Depends(entity_label_queries),
) -> EntityLabelResponse:
    """Libellé d'une revue ou d'un éditeur par son identifiant.

    Sert à réafficher une pastille de facette restaurée depuis l'URL, qui porte l'identifiant seul : il est l'état canonique de la sélection. Le libellé étant le même sous tous les jeux de filtres, la lecture est unique quel que soit le contexte qui affiche la facette.
    """
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)
