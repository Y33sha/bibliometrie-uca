"""Configuration router — paramètres applicatifs et périmètres."""

import json
from fastapi import APIRouter, HTTPException
from backend.deps import get_cursor
from utils.perimeter import get_perimeter_structure_ids

router = APIRouter()


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
    try:
        value_json = json.dumps(data["value"])
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Valeur JSON invalide : {e}")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT key FROM config WHERE key = %s", (key,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Paramètre '{key}' introuvable")
        cur.execute("""
            UPDATE config SET value = %s::jsonb, updated_at = now()
            WHERE key = %s
            RETURNING key, value, description, updated_at
        """, (value_json, key))
        return cur.fetchone()


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
                cur.execute("""
                    SELECT id, name, acronym, code FROM structures
                    WHERE id = ANY(%s) ORDER BY name
                """, (root_ids,))
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
        cur.execute("""
            UPDATE perimeters
            SET structure_ids = array_append(structure_ids, %s)
            WHERE id = %s AND NOT structure_ids @> ARRAY[%s]
            RETURNING id
        """, (structure_id, perimeter_id, structure_id))
        if not cur.fetchone():
            # Vérifier si le périmètre existe
            cur.execute("SELECT id FROM perimeters WHERE id = %s", (perimeter_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Périmètre introuvable")
            # Structure déjà présente
            return {"status": "already_present"}
        return {"status": "added"}


@router.delete("/api/perimeters/{perimeter_id}/structures/{structure_id}")
async def remove_perimeter_structure(perimeter_id: int, structure_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("""
            UPDATE perimeters
            SET structure_ids = array_remove(structure_ids, %s)
            WHERE id = %s
            RETURNING id
        """, (structure_id, perimeter_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Périmètre introuvable")
        return {"status": "removed"}
