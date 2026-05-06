"""Router périmètres — définition des ensembles de structures UCA.

Un `perimeter` (table `perimeters`) nomme un ensemble de structures
racines (colonne `structure_ids`) ; l'ensemble effectif est résolu par
la CTE récursive `async_get_perimeter_structure_ids` (descend
est_tutelle_de et est_partenaire_de).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from application import config as config_service
from application.ports.config import AsyncConfigStore
from application.ports.perimeters_queries import AsyncPerimetersAdminQueries
from domain.ports.perimeter_repository import AsyncPerimeterRepository
from interfaces.api.async_deps import (
    config_store,
    db_conn,
    perimeter_repo,
    perimeters_admin_queries,
)
from interfaces.api.models import (
    AddPerimeterStructure,
    CreatedIdResponse,
    OkResponse,
    PerimeterCreate,
    PerimeterOut,
    PerimeterUpdate,
    StatusResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/perimeters", response_model=list[PerimeterOut])
async def list_perimeters(
    queries: AsyncPerimetersAdminQueries = Depends(perimeters_admin_queries),
) -> Any:
    """Liste tous les périmètres avec leurs structures racines résolues.

    Pour chaque périmètre, renvoie les structures racines directes
    (`structures`) et le décompte total après descente récursive des
    relations (`structure_count`). Le décompte inclut donc les
    sous-structures rattachées par `est_tutelle_de` / `est_partenaire_de`.
    """
    return await queries.list_perimeters_with_structures()


@router.post("/api/perimeters", response_model=CreatedIdResponse)
async def create_perimeter(
    body: PerimeterCreate,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPerimeterRepository = Depends(perimeter_repo),
) -> Any:
    """Crée un nouveau périmètre."""
    code = body.code.strip()
    name = body.name.strip()
    description = (body.description or "").strip() or None
    pid = await config_service.create_perimeter(
        conn,
        code=code,
        name=name,
        description=description,
        repo=repo,
    )
    return {"id": pid}


@router.put("/api/perimeters/{perimeter_id}", response_model=OkResponse)
async def update_perimeter(
    perimeter_id: int,
    body: PerimeterUpdate,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPerimeterRepository = Depends(perimeter_repo),
) -> Any:
    """Met à jour un périmètre (nom, description, structures)."""
    fields = body.model_dump(exclude_unset=True)
    # Nettoyer : strip des strings et description vide → None
    if "name" in fields and isinstance(fields["name"], str):
        fields["name"] = fields["name"].strip()
    if "description" in fields and isinstance(fields["description"], str):
        fields["description"] = fields["description"].strip() or None
    await config_service.update_perimeter(conn, perimeter_id, fields=fields, repo=repo)
    return {"ok": True}


@router.delete("/api/perimeters/{perimeter_id}", response_model=OkResponse)
async def delete_perimeter(
    perimeter_id: int,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPerimeterRepository = Depends(perimeter_repo),
    config_repo: AsyncConfigStore = Depends(config_store),
) -> Any:
    """Supprime un périmètre (interdit si utilisé dans la config pipeline)."""
    await config_service.delete_perimeter(conn, perimeter_id, repo=repo, config=config_repo)
    return {"ok": True}


@router.post("/api/perimeters/{perimeter_id}/structures", response_model=StatusResponse)
async def add_perimeter_structure(
    perimeter_id: int,
    body: AddPerimeterStructure,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPerimeterRepository = Depends(perimeter_repo),
) -> Any:
    """Ajoute une structure racine au périmètre.

    Renvoie `{"status": "added"}` ou `"already_exists"` si la
    structure était déjà racine.
    """
    status = await config_service.add_perimeter_structure(
        conn, perimeter_id, body.structure_id, repo=repo
    )
    return {"status": status}


@router.delete(
    "/api/perimeters/{perimeter_id}/structures/{structure_id}", response_model=StatusResponse
)
async def remove_perimeter_structure(
    perimeter_id: int,
    structure_id: int,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPerimeterRepository = Depends(perimeter_repo),
) -> Any:
    """Retire une structure racine du périmètre. N'affecte pas ses
    sous-structures tant qu'elles sont rattachées à d'autres racines."""
    await config_service.remove_perimeter_structure(conn, perimeter_id, structure_id, repo=repo)
    return {"status": "removed"}
