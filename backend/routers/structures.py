"""Auto-extracted router."""

from fastapi import APIRouter, Query, HTTPException, Depends
from backend.deps import get_cursor, require_admin
from backend.models import (StructureCreate, StructureUpdate, RelationCreate,
    NameFormCreate, NameFormUpdate)
from utils.normalize import normalize_text

router = APIRouter()






@router.get("/api/structures")
async def list_structures(
    type: str | None = Query(None),
    search: str = Query(""),
):
    with get_cursor() as (cur, conn):
        conditions = []
        params = []

        if type:
            conditions.append("s.structure_type::text = %s")
            params.append(type)
        if search:
            conditions.append("(unaccent(s.name) ILIKE unaccent(%s) OR s.acronym ILIKE %s OR s.code ILIKE %s)")
            params.extend([f"%{search}%"] * 3)

        where = " AND ".join(conditions) if conditions else "TRUE"

        cur.execute(f"""
            SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type
            FROM structures s
            WHERE {where}
            ORDER BY s.structure_type, s.name
        """, params)
        return cur.fetchall()


@router.get("/api/structures/{structure_id}")
async def get_structure(structure_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT id, code, name, acronym, structure_type::text AS type,
                   ror_id, rnsr_id, hal_collection
            FROM structures WHERE id = %s
        """, (structure_id,))
        structure = cur.fetchone()
        if not structure:
            raise HTTPException(status_code=404, detail="Structure not found")

        # Relations : ses tutelles (parents)
        cur.execute("""
            SELECT sr.id AS relation_id, sr.relation_type::text,
                   sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS struct_type
            FROM structure_relations sr
            JOIN structures sp ON sp.id = sr.parent_id
            WHERE sr.child_id = %s
            ORDER BY sr.relation_type, sp.name
        """, (structure_id,))
        parents = cur.fetchall()

        # Relations : ses enfants
        cur.execute("""
            SELECT sr.id AS relation_id, sr.relation_type::text,
                   sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS struct_type
            FROM structure_relations sr
            JOIN structures sc ON sc.id = sr.child_id
            WHERE sr.parent_id = %s
            ORDER BY sr.relation_type, sc.name
        """, (structure_id,))
        children = cur.fetchall()

        # Formes de noms
        cur.execute("""
            SELECT * FROM structure_name_forms
            WHERE structure_id = %s
            ORDER BY is_active DESC, form_text
        """, (structure_id,))
        forms = cur.fetchall()

        return {
            "structure": structure,
            "parents": parents,
            "children": children,
            "forms": forms,
        }


@router.post("/api/structures")
async def create_structure(data: StructureCreate):
    with get_cursor() as (cur, conn):
        cur.execute("""
            INSERT INTO structures (code, name, acronym, structure_type, ror_id, rnsr_id, hal_collection)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (data.code, data.name, data.acronym, data.type,
              data.ror_id, data.rnsr_id, data.hal_collection))
        return cur.fetchone()


@router.put("/api/structures/{structure_id}")
async def update_structure(structure_id: int, data: StructureUpdate):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM structures WHERE id = %s", (structure_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Structure not found")

        updates = []
        params = []
        field_map = {"name": "name", "acronym": "acronym", "type": "structure_type",
                     "ror_id": "ror_id", "rnsr_id": "rnsr_id", "hal_collection": "hal_collection"}
        for field_name, col_name in field_map.items():
            val = getattr(data, field_name, None)
            if val is not None:
                updates.append(f"{col_name} = %s")
                params.append(val)

        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")

        params.append(structure_id)
        cur.execute(f"""
            UPDATE structures SET {', '.join(updates)} WHERE id = %s RETURNING *
        """, params)
        return cur.fetchone()


@router.delete("/api/structures/{structure_id}")
async def delete_structure(structure_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM structures WHERE id = %s", (structure_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Structure not found")
        return {"deleted": True}


@router.post("/api/structure-relations")
async def create_relation(data: RelationCreate):
    with get_cursor() as (cur, conn):
        cur.execute("""
            INSERT INTO structure_relations (parent_id, child_id, relation_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (parent_id, child_id, relation_type) DO NOTHING
            RETURNING *
        """, (data.parent_id, data.child_id, data.relation_type))
        row = cur.fetchone()
        if not row:
            return {"status": "already_exists"}
        return row


@router.delete("/api/structure-relations/{relation_id}")
async def delete_relation(relation_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM structure_relations WHERE id = %s", (relation_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Relation not found")
        return {"deleted": True}


@router.get("/api/name-forms/{form_id}")
async def get_name_form(form_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT * FROM structure_name_forms WHERE id = %s", (form_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Form not found")
        return row


@router.post("/api/name-forms")
async def create_name_form(data: NameFormCreate):
    import json as _json
    with get_cursor() as (cur, conn):
        form_normalized = normalize_text(data.form_text)
        ctx_json = _json.dumps(data.requires_context_of) if data.requires_context_of else None
        cur.execute("""
            INSERT INTO structure_name_forms (structure_id, form_text, form_normalized, is_regex,
                                    requires_context_of, notes)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            RETURNING *
        """, (data.structure_id, data.form_text, form_normalized, data.is_regex,
              ctx_json, data.notes))
        return cur.fetchone()


@router.put("/api/name-forms/{form_id}")
async def update_name_form(form_id: int, data: NameFormUpdate):
    import json as _json
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM structure_name_forms WHERE id = %s", (form_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Name form not found")

        updates = []
        params = []

        if data.form_text is not None:
            updates.append("form_text = %s")
            params.append(data.form_text)
            updates.append("form_normalized = %s")
            params.append(normalize_text(data.form_text))
        if data.is_regex is not None:
            updates.append("is_regex = %s")
            params.append(data.is_regex)
        if data.requires_context_of is not None:
            updates.append("requires_context_of = %s::jsonb")
            params.append(_json.dumps(data.requires_context_of) if data.requires_context_of else None)
        if data.is_active is not None:
            updates.append("is_active = %s")
            params.append(data.is_active)
        if data.notes is not None:
            updates.append("notes = %s")
            params.append(data.notes)

        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")

        params.append(form_id)
        cur.execute(f"""
            UPDATE structure_name_forms SET {', '.join(updates)} WHERE id = %s RETURNING *
        """, params)
        return cur.fetchone()


@router.delete("/api/name-forms/{form_id}")
async def delete_name_form(form_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM structure_name_forms WHERE id = %s", (form_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Name form not found")
        return {"deleted": True}


# =============================================================
# HAL STRUCTURES MAPPING
# =============================================================


@router.get("/api/structures/{structure_id}/hal-mappings")
async def list_hal_mappings(structure_id: int):
    """Liste les hal_structures mappées vers cette structure."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT hal_struct_id, name, acronym, type, doc_count, valid,
                   start_date, end_date, country, rnsr, ror, code
            FROM hal_structures
            WHERE structure_id = %s
            ORDER BY start_date DESC NULLS LAST, name
        """, (structure_id,))
        return cur.fetchall()


@router.get("/api/hal-structures")
async def list_hal_structures(
    search: str = Query(""),
    unmapped: bool = Query(False),
    limit: int = Query(50),
):
    """Recherche de hal_structures. Si unmapped=true, seulement les non mappées."""
    with get_cursor() as (cur, conn):
        conditions = []
        params = []

        if unmapped:
            conditions.append("hs.structure_id IS NULL")
        if search:
            conditions.append(
                "(unaccent(hs.name) ILIKE unaccent(%s) OR hs.acronym ILIKE %s OR hs.code ILIKE %s)")
            params.extend([f"%{search}%"] * 3)

        where = " AND ".join(conditions) if conditions else "TRUE"
        cur.execute(f"""
            SELECT hs.hal_struct_id, hs.name, hs.acronym, hs.type, hs.doc_count,
                   hs.valid, hs.country, hs.code, hs.structure_id,
                   s.name AS mapped_name, s.acronym AS mapped_acronym
            FROM hal_structures hs
            LEFT JOIN structures s ON s.id = hs.structure_id
            WHERE {where}
            ORDER BY hs.doc_count DESC NULLS LAST, hs.name
            LIMIT %s
        """, params + [limit])
        return cur.fetchall()


@router.put("/api/hal-structures/{hal_struct_id}/map")
async def map_hal_structure(hal_struct_id: int, data: dict):
    """Mapper une hal_structure vers une structure canonique."""
    structure_id = data.get("structure_id")
    if not structure_id:
        raise HTTPException(status_code=400, detail="structure_id requis")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM structures WHERE id = %s", (structure_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Structure introuvable")

        cur.execute("""
            UPDATE hal_structures SET structure_id = %s
            WHERE hal_struct_id = %s
            RETURNING hal_struct_id
        """, (structure_id, hal_struct_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="HAL structure introuvable")

        return {"mapped": True}


@router.delete("/api/hal-structures/{hal_struct_id}/map")
async def unmap_hal_structure(hal_struct_id: int):
    """Supprimer le mapping d'une hal_structure."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            UPDATE hal_structures SET structure_id = NULL
            WHERE hal_struct_id = %s
            RETURNING hal_struct_id
        """, (hal_struct_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="HAL structure introuvable")

        return {"unmapped": True}


# =============================================================
# AUTHORSHIPS (auteurs UCA)
# =============================================================

