"""Auto-extracted router."""

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.deps import get_cursor
from backend.models import (
    NameFormCreate,
    NameFormUpdate,
    RelationCreate,
    StructureCreate,
    StructureUpdate,
)
from services import structures as structures_service

router = APIRouter()
logger = logging.getLogger(__name__)


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
            conditions.append(
                "(unaccent(s.name) ILIKE unaccent(%s) OR s.acronym ILIKE %s OR s.code ILIKE %s)"
            )
            params.extend([f"%{search}%"] * 3)

        where = " AND ".join(conditions) if conditions else "TRUE"

        cur.execute(
            f"""
            SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type
            FROM structures s
            WHERE {where}
            ORDER BY CASE s.structure_type::text
                WHEN 'labo' THEN 1
                WHEN 'universite' THEN 2
                WHEN 'onr' THEN 3
                WHEN 'chu' THEN 4
                WHEN 'ecole' THEN 5
                WHEN 'site' THEN 6
                ELSE 7
            END, s.name
        """,
            params,
        )
        return cur.fetchall()


@router.get("/api/structures/{structure_id}")
async def get_structure(structure_id: int):
    with get_cursor() as (cur, conn):
        cur.execute(
            """
            SELECT id, code, name, acronym, structure_type::text AS type,
                   ror_id, rnsr_id, hal_collection, api_ids
            FROM structures WHERE id = %s
        """,
            (structure_id,),
        )
        structure = cur.fetchone()
        if not structure:
            raise HTTPException(status_code=404, detail="Structure not found")

        # Relations : ses tutelles (parents)
        cur.execute(
            """
            SELECT sr.id AS relation_id, sr.relation_type::text,
                   sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS struct_type
            FROM structure_relations sr
            JOIN structures sp ON sp.id = sr.parent_id
            WHERE sr.child_id = %s
            ORDER BY sr.relation_type, sp.name
        """,
            (structure_id,),
        )
        parents = cur.fetchall()

        # Relations : ses enfants
        cur.execute(
            """
            SELECT sr.id AS relation_id, sr.relation_type::text,
                   sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS struct_type
            FROM structure_relations sr
            JOIN structures sc ON sc.id = sr.child_id
            WHERE sr.parent_id = %s
            ORDER BY sr.relation_type, sc.name
        """,
            (structure_id,),
        )
        children = cur.fetchall()

        # Formes de noms
        cur.execute(
            """
            SELECT * FROM structure_name_forms
            WHERE structure_id = %s
            ORDER BY form_text
        """,
            (structure_id,),
        )
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
        return structures_service.create_structure(
            cur,
            code=data.code,
            name=data.name,
            acronym=data.acronym,
            type=data.type,
            ror_id=data.ror_id,
            rnsr_id=data.rnsr_id,
            hal_collection=data.hal_collection,
            api_ids=data.api_ids,
        )


@router.put("/api/structures/{structure_id}")
async def update_structure(structure_id: int, data: StructureUpdate):
    fields = data.model_dump(exclude_unset=True)
    with get_cursor() as (cur, conn):
        try:
            row = structures_service.update_structure(cur, structure_id, fields=fields)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if row is None:
            raise HTTPException(status_code=404, detail="Structure not found")
        return row


@router.delete("/api/structures/{structure_id}")
async def delete_structure(structure_id: int):
    with get_cursor() as (cur, conn):
        if not structures_service.delete_structure(cur, structure_id):
            raise HTTPException(status_code=404, detail="Structure not found")
        return {"deleted": True}


@router.post("/api/structure-relations")
async def create_relation(data: RelationCreate):
    with get_cursor() as (cur, conn):
        row = structures_service.create_relation(
            cur,
            parent_id=data.parent_id,
            child_id=data.child_id,
            relation_type=data.relation_type,
        )
        if row is None:
            return {"status": "already_exists"}
        return row


@router.delete("/api/structure-relations/{relation_id}")
async def delete_relation(relation_id: int):
    with get_cursor() as (cur, conn):
        if not structures_service.delete_relation(cur, relation_id):
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
    with get_cursor() as (cur, conn):
        return structures_service.create_name_form(
            cur,
            structure_id=data.structure_id,
            form_text=data.form_text,
            is_word_boundary=data.is_word_boundary,
            is_excluding=data.is_excluding,
            requires_context_of=data.requires_context_of,
        )


@router.put("/api/name-forms/{form_id}")
async def update_name_form(form_id: int, data: NameFormUpdate):
    fields = data.model_dump(exclude_unset=True)
    with get_cursor() as (cur, conn):
        try:
            row = structures_service.update_name_form(cur, form_id, fields=fields)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if row is None:
            raise HTTPException(status_code=404, detail="Name form not found")
        return row


@router.delete("/api/name-forms/{form_id}")
async def delete_name_form(form_id: int):
    with get_cursor() as (cur, conn):
        if not structures_service.delete_name_form(cur, form_id):
            raise HTTPException(status_code=404, detail="Name form not found")
        return {"deleted": True}


# =============================================================

# =============================================================
# AUTHORSHIPS (auteurs UCA)
# =============================================================
