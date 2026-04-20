"""Router périmètres — définition des ensembles de structures UCA.

Un `perimeter` (table `perimeters`) nomme un ensemble de structures
racines (colonne `structure_ids`) ; l'ensemble effectif est résolu par
`infrastructure.perimeter.get_perimeter_structure_ids` qui descend les
relations (est_tutelle_de, est_partenaire_de).
"""

import logging
from typing import Any

from fastapi import APIRouter

from application import config as config_service
from infrastructure.perimeter import get_perimeter_structure_ids
from infrastructure.repositories import config_repository
from interfaces.api.deps import get_cursor
from interfaces.api.models import (
    AddPerimeterStructure,
    PerimeterCreate,
    PerimeterUpdate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/perimeters")
async def list_perimeters() -> Any:
    with get_cursor() as (cur, _conn):
        cur.execute("SELECT id, code, name, description, structure_ids FROM perimeters ORDER BY id")
        perimeters = cur.fetchall()
        for p in perimeters:
            # Résoudre les noms des structures racines
            root_ids = p["structure_ids"] or []
            if root_ids:
                cur.execute(
                    """
                    SELECT id, name, acronym, code FROM structures
                    WHERE id = ANY(%s) ORDER BY name
                """,
                    (root_ids,),
                )
                p["structures"] = cur.fetchall()
            else:
                p["structures"] = []
            resolved = get_perimeter_structure_ids(cur, p["code"])
            p["structure_count"] = len(resolved)
        return perimeters


@router.post("/api/perimeters")
async def create_perimeter(body: PerimeterCreate) -> Any:
    """Crée un nouveau périmètre."""
    code = body.code.strip()
    name = body.name.strip()
    description = (body.description or "").strip() or None
    with get_cursor() as (cur, _conn):
        pid = config_service.create_perimeter(
            cur, code=code, name=name, description=description, repo=config_repository(cur)
        )
        return {"id": pid}


@router.put("/api/perimeters/{perimeter_id}")
async def update_perimeter(perimeter_id: int, body: PerimeterUpdate) -> Any:
    """Met à jour un périmètre (nom, description, structures)."""
    fields = body.model_dump(exclude_unset=True)
    # Nettoyer : strip des strings et description vide → None
    if "name" in fields and isinstance(fields["name"], str):
        fields["name"] = fields["name"].strip()
    if "description" in fields and isinstance(fields["description"], str):
        fields["description"] = fields["description"].strip() or None
    with get_cursor() as (cur, _conn):
        config_service.update_perimeter(
            cur, perimeter_id, fields=fields, repo=config_repository(cur)
        )
        return {"ok": True}


@router.delete("/api/perimeters/{perimeter_id}")
async def delete_perimeter(perimeter_id: int) -> Any:
    """Supprime un périmètre (interdit si utilisé dans la config pipeline)."""
    with get_cursor() as (cur, _conn):
        config_service.delete_perimeter(cur, perimeter_id, repo=config_repository(cur))
        return {"ok": True}


@router.post("/api/perimeters/{perimeter_id}/structures")
async def add_perimeter_structure(perimeter_id: int, body: AddPerimeterStructure) -> Any:
    with get_cursor() as (cur, _conn):
        status = config_service.add_perimeter_structure(
            cur, perimeter_id, body.structure_id, repo=config_repository(cur)
        )
        return {"status": status}


@router.delete("/api/perimeters/{perimeter_id}/structures/{structure_id}")
async def remove_perimeter_structure(perimeter_id: int, structure_id: int) -> Any:
    with get_cursor() as (cur, _conn):
        config_service.remove_perimeter_structure(
            cur, perimeter_id, structure_id, repo=config_repository(cur)
        )
        return {"status": "removed"}
