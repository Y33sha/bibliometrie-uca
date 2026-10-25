"""Router des ensembles de structures que les phases du pipeline consomment. Sert `/api/perimeters/*`.

Un périmètre (table `perimeters`) nomme des structures racines dans sa colonne `structure_ids`. L'ensemble effectif y ajoute leurs descendants dans `structure_parents`. Cet ensemble est matérialisé dans `perimeter_structures` par `PerimeterStructures.refresh` ; les lectures le restituent sans le recalculer.
"""

from fastapi import APIRouter, Depends

from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.read_models.config_queries import ConfigQueries
from application.ports.read_models.perimeters_queries import PerimeterOut, PerimetersQueries
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from application.services import perimeters as perimeters_service
from interfaces.api.deps import (
    DbConn,
    config_queries,
    get_perimeter_structures,
    perimeter_repo,
    perimeters_queries,
)
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
    conn: DbConn,
    repo: PerimeterRepository = Depends(perimeter_repo),
    perimeter_structures: PerimeterStructures = Depends(get_perimeter_structures),
) -> CreatedIdResponse:
    """Crée un périmètre avec ses structures racines, la liste pouvant être vide.

    Le code sert d'identifiant naturel — la configuration du pipeline désigne un périmètre par sa valeur — et doit être un jeton unique, sans espace : un code vide ou espacé rend 422. Renvoie 409 sur un code déjà pris.
    """
    pid = perimeters_service.create_perimeter(
        code=body.code,
        name=body.name,
        root_structure_ids=body.root_structure_ids,
        conn=conn,
        repo=repo,
        perimeter_structures=perimeter_structures,
    )
    return CreatedIdResponse(id=pid)


@router.put("/{perimeter_id}", response_model=OkResponse)
def update_perimeter(
    perimeter_id: int,
    body: PerimeterUpdate,
    conn: DbConn,
    repo: PerimeterRepository = Depends(perimeter_repo),
    perimeter_structures: PerimeterStructures = Depends(get_perimeter_structures),
) -> OkResponse:
    """Met à jour un périmètre (nom, structures racines).

    Seuls les champs fournis sont écrits ; un corps vide rend 422, un périmètre inconnu 404. La clôture matérialisée suit le changement de racines.
    """
    perimeters_service.update_perimeter(
        perimeter_id,
        update=body,
        conn=conn,
        repo=repo,
        perimeter_structures=perimeter_structures,
    )
    return OkResponse()


@router.delete("/{perimeter_id}", response_model=OkResponse)
def delete_perimeter(
    perimeter_id: int,
    repo: PerimeterRepository = Depends(perimeter_repo),
    config: ConfigQueries = Depends(config_queries),
) -> OkResponse:
    """Supprime un périmètre.

    Renvoie 409 si une clé de configuration le désigne encore — le pipeline s'y appuierait sans le trouver. Les lignes de la clôture matérialisée s'en vont avec lui, par cascade.
    """
    perimeters_service.delete_perimeter(perimeter_id, repo=repo, config=config)
    return OkResponse()
