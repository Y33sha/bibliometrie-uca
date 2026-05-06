"""Router périmètres — définition des ensembles de structures UCA.

Un `perimeter` (table `perimeters`) nomme un ensemble de structures
racines (colonne `structure_ids`) ; l'ensemble effectif est résolu par
`infrastructure.perimeter.async_get_perimeter_structure_ids` qui descend
les relations (est_tutelle_de, est_partenaire_de).
"""

import logging
from typing import Any

from fastapi import APIRouter

from application import config as config_service
from infrastructure.perimeter import async_get_perimeter_structure_ids
from infrastructure.repositories import async_config_store, async_perimeter_repository
from interfaces.api.async_deps import get_async_cursor, get_sa_connection
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
async def list_perimeters() -> Any:
    """Liste tous les périmètres avec leurs structures racines résolues.

    Pour chaque périmètre, renvoie les structures racines directes
    (`structures`) et le décompte total après descente récursive des
    relations (`structure_count`). Le décompte inclut donc les
    sous-structures rattachées par `est_tutelle_de` / `est_partenaire_de`.
    """
    # Endpoint pas encore migré en SA : il dépend d'`infrastructure.perimeter`
    # (CTE récursive) qui n'est pas encore migrée. À traiter quand on
    # touchera ce module.
    async with get_async_cursor() as (cur, _conn):
        await cur.execute(
            "SELECT id, code, name, description, structure_ids FROM perimeters ORDER BY id"
        )
        perimeters = await cur.fetchall()
        for p in perimeters:
            root_ids = p["structure_ids"] or []
            if root_ids:
                await cur.execute(
                    """
                    SELECT id, name, acronym, code FROM structures
                    WHERE id = ANY(%s) ORDER BY name
                """,
                    (root_ids,),
                )
                p["structures"] = await cur.fetchall()
            else:
                p["structures"] = []
            resolved = await async_get_perimeter_structure_ids(cur, p["code"])
            p["structure_count"] = len(resolved)
        return perimeters


@router.post("/api/perimeters", response_model=CreatedIdResponse)
async def create_perimeter(body: PerimeterCreate) -> Any:
    """Crée un nouveau périmètre."""
    code = body.code.strip()
    name = body.name.strip()
    description = (body.description or "").strip() or None
    async with get_sa_connection() as conn:
        pid = await config_service.create_perimeter(
            conn,
            code=code,
            name=name,
            description=description,
            repo=async_perimeter_repository(conn),
        )
        return {"id": pid}


@router.put("/api/perimeters/{perimeter_id}", response_model=OkResponse)
async def update_perimeter(perimeter_id: int, body: PerimeterUpdate) -> Any:
    """Met à jour un périmètre (nom, description, structures)."""
    fields = body.model_dump(exclude_unset=True)
    # Nettoyer : strip des strings et description vide → None
    if "name" in fields and isinstance(fields["name"], str):
        fields["name"] = fields["name"].strip()
    if "description" in fields and isinstance(fields["description"], str):
        fields["description"] = fields["description"].strip() or None
    async with get_sa_connection() as conn:
        await config_service.update_perimeter(
            conn, perimeter_id, fields=fields, repo=async_perimeter_repository(conn)
        )
        return {"ok": True}


@router.delete("/api/perimeters/{perimeter_id}", response_model=OkResponse)
async def delete_perimeter(perimeter_id: int) -> Any:
    """Supprime un périmètre (interdit si utilisé dans la config pipeline)."""
    async with get_sa_connection() as conn:
        await config_service.delete_perimeter(
            conn,
            perimeter_id,
            repo=async_perimeter_repository(conn),
            config=async_config_store(conn),
        )
        return {"ok": True}


@router.post("/api/perimeters/{perimeter_id}/structures", response_model=StatusResponse)
async def add_perimeter_structure(perimeter_id: int, body: AddPerimeterStructure) -> Any:
    """Ajoute une structure racine au périmètre.

    Renvoie `{"status": "added"}` ou `"already_exists"` si la
    structure était déjà racine.
    """
    async with get_sa_connection() as conn:
        status = await config_service.add_perimeter_structure(
            conn, perimeter_id, body.structure_id, repo=async_perimeter_repository(conn)
        )
        return {"status": status}


@router.delete(
    "/api/perimeters/{perimeter_id}/structures/{structure_id}", response_model=StatusResponse
)
async def remove_perimeter_structure(perimeter_id: int, structure_id: int) -> Any:
    """Retire une structure racine du périmètre. N'affecte pas ses
    sous-structures tant qu'elles sont rattachées à d'autres racines."""
    async with get_sa_connection() as conn:
        await config_service.remove_perimeter_structure(
            conn, perimeter_id, structure_id, repo=async_perimeter_repository(conn)
        )
        return {"status": "removed"}
