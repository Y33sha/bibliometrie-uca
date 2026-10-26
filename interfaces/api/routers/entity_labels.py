"""Router du libellé d'une entité de facette, servi par `EntityLabelQueries`. Sert `/api/entity-labels`."""

from fastapi import APIRouter, Depends, Query

from infrastructure.read_models._common import EntityKind
from infrastructure.read_models.entity_labels import EntityLabelQueries
from infrastructure.read_models.entity_labels.models import (
    EntityLabelResponse,
)
from interfaces.api.deps import entity_label_queries

router = APIRouter(prefix="/api/entity-labels", tags=["entity-labels"])


@router.get("", response_model=EntityLabelResponse)
def resolve_entity_label(
    kind: EntityKind = Query(...),
    entity_id: str = Query(...),
    queries: EntityLabelQueries = Depends(entity_label_queries),
) -> EntityLabelResponse:
    """Libellé d'une entité de facette par son identifiant : un entier, ou un ROR pour une organisation partenaire.

    Sert à réafficher une pastille de facette restaurée depuis l'URL, qui porte l'identifiant seul : il est l'état canonique de la sélection. Le libellé étant le même sous tous les jeux de filtres, la lecture est unique quel que soit le contexte qui affiche la facette.
    """
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)
