"""Router des ensembles de structures que les phases du pipeline consomment. Sert `/api/perimeters/*`.

Un périmètre (table `perimeters`) nomme des structures racines (`root_structure_ids`). Ses structures sont ces racines et leurs descendantes dans `structure_parents`, matérialisées dans `perimeter_structures` par `PerimeterStructures.refresh` ; les lectures les lisent sans les recalculer.
"""

from fastapi import APIRouter, Depends

from application.ports.repositories.perimeter_repository import PerimeterUpdate
from application.services.perimeters import PerimeterService
from infrastructure.read_models.perimeters.models import (
    PerimeterCountryOut,
    PerimeterOut,
)
from infrastructure.read_models.perimeters.queries import PerimetersQueries
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

    `structures` contient seulement les racines ; `structure_count` compte toutes les structures du périmètre, racines et descendantes.
    """
    return queries.list_perimeters_with_structures()


@router.get("/countries", response_model=list[PerimeterCountryOut])
def list_perimeter_countries(
    queries: PerimetersQueries = Depends(perimeters_queries),
) -> list[PerimeterCountryOut]:
    """Pays des organisations ROR des structures du périmètre des personnes, du plus fréquent au moins fréquent. Sert à choisir le pays de l'établissement."""
    return queries.persons_perimeter_countries()


@router.post("", response_model=CreatedIdResponse)
def create_perimeter(
    body: PerimeterCreate,
    perimeters: PerimeterService = Depends(perimeter_service),
) -> CreatedIdResponse:
    """Crée un périmètre avec ses structures racines, la liste pouvant être vide.

    Le code est un identifiant naturel : la configuration du pipeline désigne un périmètre par sa valeur. C'est un jeton unique, sans espace ; un code vide ou espacé renvoie 422. Renvoie 409 sur un code déjà pris.
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

    Seuls les champs fournis sont écrits ; un corps vide renvoie 422, un périmètre inconnu 404. Les structures du périmètre suivent le changement de racines.
    """
    perimeters.update_perimeter(perimeter_id, body)
    return OkResponse()


@router.delete("/{perimeter_id}", response_model=OkResponse)
def delete_perimeter(
    perimeter_id: int,
    perimeters: PerimeterService = Depends(perimeter_service),
) -> OkResponse:
    """Supprime un périmètre.

    Renvoie 409 si une clé de configuration le désigne : le pipeline le chercherait en vain. Ses lignes de `perimeter_structures` partent en cascade.
    """
    perimeters.delete_perimeter(perimeter_id)
    return OkResponse()
