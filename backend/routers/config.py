"""Configuration router — paramètres applicatifs et périmètres."""

import json
from fastapi import APIRouter, HTTPException
from backend.deps import get_cursor
from utils.uca_perimeter import get_perimeter_structure_ids

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
        cur.execute("SELECT id, code, name, description FROM perimeters ORDER BY id")
        perimeters = cur.fetchall()
        for p in perimeters:
            pid = p["id"]
            cur.execute("""
                SELECT pr.id, pr.structure_id, pr.include_children, s.name, s.acronym, s.code
                FROM perimeter_rules pr
                JOIN structures s ON s.id = pr.structure_id
                WHERE pr.perimeter_id = %s
                ORDER BY s.name
            """, (pid,))
            p["rules"] = cur.fetchall()
            resolved = get_perimeter_structure_ids(cur, p["code"])
            p["structure_count"] = len(resolved)
        return perimeters


@router.post("/api/perimeters/{perimeter_id}/rules")
async def add_perimeter_rule(perimeter_id: int, data: dict):
    structure_id = data.get("structure_id")
    include_children = data.get("include_children", True)
    if not structure_id:
        raise HTTPException(status_code=400, detail="structure_id requis")

    with get_cursor() as (cur, conn):
        cur.execute("""
            INSERT INTO perimeter_rules (perimeter_id, structure_id, include_children)
            VALUES (%s, %s, %s)
            ON CONFLICT (perimeter_id, structure_id) DO UPDATE SET include_children = EXCLUDED.include_children
            RETURNING id
        """, (perimeter_id, structure_id, include_children))
        return cur.fetchone()


@router.delete("/api/perimeter-rules/{rule_id}")
async def delete_perimeter_rule(rule_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM perimeter_rules WHERE id = %s", (rule_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Règle introuvable")
        return {"deleted": True}
