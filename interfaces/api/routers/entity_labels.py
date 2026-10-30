"""Router du libellé d'une entité de facette, servi par `EntityLabelQueries`. Sert `/api/entity-labels`."""

from fastapi import APIRouter, Depends, Query

from infrastructure.read_models._common import EntityKind
from infrastructure.read_models.entity_labels.models import (
    EntityLabelResponse,
)
from infrastructure.read_models.entity_labels.queries import EntityLabelQueries
from interfaces.api.deps import entity_label_queries

router = APIRouter(prefix="/api/entity-labels", tags=["entity-labels"])


@router.get("", response_model=EntityLabelResponse)
def resolve_entity_label(
    kind: EntityKind = Query(...),
    entity_id: str = Query(...),
    queries: EntityLabelQueries = Depends(entity_label_queries),
) -> EntityLabelResponse:
    """Renvoie le libellé d'une entité de facette par son identifiant : un entier, ou un ROR pour une organisation partenaire.

    Sert à réafficher une pastille de facette restaurée depuis l'URL, qui contient seulement l'identifiant. Le libellé est le même sous tous les filtres : une seule lecture sert tous les contextes.
    """
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)
