"""Configuration router — paramètres applicatifs et périmètres."""

import logging

from fastapi import APIRouter, HTTPException

from backend.deps import get_cursor
from services import config as config_service
from utils.perimeter import get_perimeter_structure_ids

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Config clé/valeur ──


@router.get("/api/config")
async def list_config():
    with get_cursor() as (cur, conn):
        cur.execute("SELECT key, value, description, updated_at FROM config ORDER BY key")
        return cur.fetchall()


@router.get("/api/config/hal-collections")
async def get_hal_collections():
    """Retourne les collections HAL dérivées des structures du périmètre UCA."""
    with get_cursor() as (cur, conn):
        from utils.app_config import get_hal_collections as _get

        collections = _get(cur)
        return {"collections": collections, "count": len(collections)}


@router.put("/api/config/{key}")
async def update_config(key: str, data: dict):
    if "value" not in data:
        raise HTTPException(status_code=400, detail="'value' requis")

    with get_cursor() as (cur, conn):
        try:
            row = config_service.update_config_value(cur, key, data["value"])
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Valeur JSON invalide : {e}")
        if row is None:
            raise HTTPException(status_code=404, detail=f"Paramètre '{key}' introuvable")
        return row


# ── Périmètres ──


@router.get("/api/perimeters")
async def list_perimeters():
    with get_cursor() as (cur, conn):
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


@router.post("/api/perimeters/{perimeter_id}/structures")
async def add_perimeter_structure(perimeter_id: int, data: dict):
    structure_id = data.get("structure_id")
    if not structure_id:
        raise HTTPException(status_code=400, detail="structure_id requis")
    with get_cursor() as (cur, conn):
        status = config_service.add_perimeter_structure(cur, perimeter_id, structure_id)
        if status == "not_found":
            raise HTTPException(status_code=404, detail="Périmètre introuvable")
        return {"status": status}


@router.delete("/api/perimeters/{perimeter_id}/structures/{structure_id}")
async def remove_perimeter_structure(perimeter_id: int, structure_id: int):
    with get_cursor() as (cur, conn):
        if not config_service.remove_perimeter_structure(cur, perimeter_id, structure_id):
            raise HTTPException(status_code=404, detail="Périmètre introuvable")
        return {"status": "removed"}


@router.post("/api/perimeters")
async def create_perimeter(data: dict):
    """Crée un nouveau périmètre."""
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Code et nom requis")
    description = (data.get("description") or "").strip() or None
    with get_cursor() as (cur, conn):
        pid = config_service.create_perimeter(cur, code=code, name=name,
                                               description=description)
        if pid is None:
            raise HTTPException(status_code=409, detail="Ce code existe déjà")
        return {"id": pid}


@router.put("/api/perimeters/{perimeter_id}")
async def update_perimeter(perimeter_id: int, data: dict):
    """Met à jour un périmètre (nom, description, structures)."""
    fields = {}
    if "name" in data:
        fields["name"] = data["name"].strip()
    if "description" in data:
        fields["description"] = data["description"].strip() or None
    if "structure_ids" in data:
        fields["structure_ids"] = data["structure_ids"]
    with get_cursor() as (cur, conn):
        try:
            found = config_service.update_perimeter(cur, perimeter_id, fields=fields)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not found:
            raise HTTPException(status_code=404, detail="Périmètre introuvable")
        return {"ok": True}


@router.delete("/api/perimeters/{perimeter_id}")
async def delete_perimeter(perimeter_id: int):
    """Supprime un périmètre (interdit si utilisé dans la config pipeline)."""
    with get_cursor() as (cur, conn):
        try:
            found = config_service.delete_perimeter(cur, perimeter_id)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if not found:
            raise HTTPException(status_code=404, detail="Périmètre introuvable")
        return {"ok": True}
