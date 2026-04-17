"""Auto-extracted router."""

import logging
import os
import sys

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.deps import get_cursor
from backend.models import AssignStructureAction
from services import addresses as addresses_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/feedback/stats")
async def feedback_stats(structure_id: int = Query(...)):
    """Statistiques de qualité de la détection pour une structure donnée."""
    with get_cursor() as (cur, conn):
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_confirmed IS NOT NULL) AS total_reviewed,
                COUNT(*) FILTER (WHERE is_confirmed = TRUE AND matched_form_id IS NOT NULL) AS concordant_valid,
                COUNT(*) FILTER (WHERE is_confirmed = FALSE AND matched_form_id IS NULL) AS concordant_rejected,
                COUNT(*) FILTER (WHERE is_confirmed = TRUE AND matched_form_id IS NULL) AS false_negatives,
                COUNT(*) FILTER (WHERE is_confirmed = FALSE AND matched_form_id IS NOT NULL) AS false_positives,
                COUNT(*) FILTER (WHERE is_confirmed IS NULL AND matched_form_id IS NOT NULL) AS pending
            FROM address_structures
            WHERE structure_id = %s
        """,
            (structure_id,),
        )
        row = cur.fetchone()

        reviewed = (
            (row["concordant_valid"] or 0)
            + (row["concordant_rejected"] or 0)
            + (row["false_negatives"] or 0)
            + (row["false_positives"] or 0)
        )
        concordant = (row["concordant_valid"] or 0) + (row["concordant_rejected"] or 0)

        return {
            "total_reviewed": reviewed,
            "detection_rate": round(concordant / reviewed * 100, 1) if reviewed else None,
            "false_negatives": row["false_negatives"] or 0,
            "false_positives": row["false_positives"] or 0,
            "concordant_valid": row["concordant_valid"] or 0,
            "pending": row["pending"] or 0,
        }


@router.get("/api/admin/feedback/false-negatives")
async def feedback_false_negatives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Adresses confirmées manuellement pour cette structure mais non détectées par le script."""
    offset = (page - 1) * per_page

    with get_cursor() as (cur, conn):
        conditions = [
            "ast.structure_id = %s",
            "ast.is_confirmed = TRUE",
            "ast.matched_form_id IS NULL",
        ]
        params: list = [structure_id]

        if search:
            conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM address_structures ast
            JOIN addresses a ON a.id = ast.address_id
            WHERE {where}
        """,
            params,
        )
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT
                a.id, a.raw_text, a.pub_count,
                (SELECT json_agg(json_build_object(
                    'structure_id', s.id, 'acronym', s.acronym, 'name', s.name,
                    'is_detected', (ast2.matched_form_id IS NOT NULL),
                    'is_confirmed', ast2.is_confirmed
                ))
                FROM address_structures ast2
                JOIN structures s ON s.id = ast2.structure_id
                WHERE ast2.address_id = a.id AND s.structure_type != 'site'
                ) AS labs
            FROM address_structures ast
            JOIN addresses a ON a.id = ast.address_id
            WHERE {where}
            ORDER BY a.pub_count DESC, a.id
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": cur.fetchall(),
        }


@router.get("/api/admin/feedback/false-positives")
async def feedback_false_positives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Adresses détectées pour cette structure mais rejetées manuellement."""
    offset = (page - 1) * per_page

    with get_cursor() as (cur, conn):
        conditions = [
            "ast.structure_id = %s",
            "ast.is_confirmed = FALSE",
            "ast.matched_form_id IS NOT NULL",
        ]
        params: list = [structure_id]

        if search:
            conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM address_structures ast
            JOIN addresses a ON a.id = ast.address_id
            WHERE {where}
        """,
            params,
        )
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT
                a.id, a.raw_text, a.pub_count,
                (SELECT json_agg(json_build_object(
                    'structure_id', s.id, 'acronym', s.acronym, 'name', s.name,
                    'is_detected', (ast2.matched_form_id IS NOT NULL),
                    'is_confirmed', ast2.is_confirmed
                ))
                FROM address_structures ast2
                JOIN structures s ON s.id = ast2.structure_id
                WHERE ast2.address_id = a.id AND s.structure_type != 'site'
                ) AS labs,
                (SELECT json_agg(json_build_object(
                    'form_id', nf.id,
                    'form_text', nf.form_text,
                    'requires_context_of', nf.requires_context_of,
                    'structure_name', COALESCE(s.acronym, s.name)
                ))
                FROM address_structures ast2
                JOIN structure_name_forms nf ON nf.id = ast2.matched_form_id
                JOIN structures s ON s.id = nf.structure_id
                WHERE ast2.address_id = a.id
                  AND ast2.structure_id = %s
                  AND ast2.matched_form_id IS NOT NULL
                ) AS matched_forms
            FROM address_structures ast
            JOIN addresses a ON a.id = ast.address_id
            WHERE {where}
            ORDER BY a.pub_count DESC, a.id
            LIMIT %s OFFSET %s
        """,
            params + [structure_id, per_page, offset],
        )

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": cur.fetchall(),
        }


@router.post("/api/addresses/{addr_id}/assign-structure")
async def assign_structure(addr_id: int, action: AssignStructureAction):
    """Assigne manuellement une structure à une adresse."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM addresses WHERE id = %s", (addr_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Address not found")

        cur.execute("SELECT id FROM structures WHERE id = %s", (action.structure_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Structure not found")

        addresses_service.review_structure_link(cur, addr_id, action.structure_id, True)
        return {"id": addr_id, "structure_id": action.structure_id, "status": "assigned"}


@router.get("/api/admin/feedback/rerun")
async def feedback_rerun():
    """Lance resolve_addresses en SSE (détection complète sur toutes les adresses)."""
    import asyncio

    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "processing",
        "resolve_addresses.py",
    )
    if not os.path.exists(script):
        raise HTTPException(status_code=500, detail="Script resolve_addresses.py introuvable")

    async def event_stream():
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=600)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    yield f"data: {text}\n\n"
            returncode = await proc.wait()
            if returncode == 0:
                yield "data: [DONE]\n\n"
            else:
                yield f"data: [ERROR] Code retour {returncode}\n\n"
        except asyncio.TimeoutError:
            proc.kill()
            yield "data: [ERROR] Timeout (>10min)\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/api/addresses/{addr_id}/assign-structure")
async def unassign_structure(addr_id: int, structure_id: int = Query(...)):
    """Supprime l'assignation manuelle d'une structure."""
    with get_cursor() as (cur, conn):
        deleted = addresses_service.unassign_manual_structure(cur, addr_id, structure_id)
        return {"deleted": deleted}


# ----- API: Labos -----
