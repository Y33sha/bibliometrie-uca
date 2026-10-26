"""Router des ensembles de structures que les phases du pipeline consomment. Sert `/api/perimeters/*`.

Un périmètre (table `perimeters`) nomme des structures racines dans sa colonne `structure_ids`. L'ensemble effectif y ajoute leurs descendants dans `structure_parents`. Cet ensemble est matérialisé dans `perimeter_structures` par `PerimeterStructures.refresh` ; les lectures le restituent sans le recalculer.
"""

from fastapi import APIRouter, Depends

from application.ports.repositories.perimeter_repository import PerimeterUpdate
from application.services.perimeters import PerimeterService
from infrastructure.read_models.perimeters import PerimetersQueries
from infrastructure.read_models.perimeters.models import (
    PerimeterOut,
)
from interfaces.api.deps import perimeter_service, perimeters_queries
from interfaces.api.models import (
    CreatedIdResponse,
    OkResponse,
    PerimeterCreate,
)

router = APIRouter(prefix="/api/perimeters", tags=["perimeters"])


@router.get("", response_model=list[PerimeterOut])
def list_perimeters(
    queries: PerimetersQueries = Depends(perimeters_queries),
) -> list[PerimeterOut]:
    """Liste les périmètres avec leurs structures racines.

    `structures` porte les seules racines ; `structure_count` compte l'ensemble effectif, racines et descendants réunis.
    """
    return queries.list_perimeters_with_structures()


@router.post("", response_model=CreatedIdResponse)
def create_perimeter(
    body: PerimeterCreate,
    perimeters: PerimeterService = Depends(perimeter_service),
) -> CreatedIdResponse:
    """Crée un périmètre avec ses structures racines, la liste pouvant être vide.

    Le code sert d'identifiant naturel — la configuration du pipeline désigne un périmètre par sa valeur — et doit être un jeton unique, sans espace : un code vide ou espacé rend 422. Renvoie 409 sur un code déjà pris.
    """
    pid = perimeters.create_perimeter(
        code=body.code, name=body.name, root_structure_ids=body.root_structure_ids
    )
    return CreatedIdResponse(id=pid)


@router.put("/{perimeter_id}", response_model=OkResponse)
def update_perimeter(
    perimeter_id: int,
    body: PerimeterUpdate,
    perimeters: PerimeterService = Depends(perimeter_service),
) -> OkResponse:
    """Met à jour un périmètre (nom, structures racines).

    Seuls les champs fournis sont écrits ; un corps vide rend 422, un périmètre inconnu 404. La clôture matérialisée suit le changement de racines.
    """
    perimeters.update_perimeter(perimeter_id, body)
    return OkResponse()


@router.delete("/{perimeter_id}", response_model=OkResponse)
def delete_perimeter(
    perimeter_id: int,
    perimeters: PerimeterService = Depends(perimeter_service),
) -> OkResponse:
    """Supprime un périmètre.

    Renvoie 409 si une clé de configuration le désigne encore — le pipeline s'y appuierait sans le trouver. Les lignes de la clôture matérialisée s'en vont avec lui, par cascade.
    """
    perimeters.delete_perimeter(perimeter_id)
    return OkResponse()
