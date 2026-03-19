"""Auto-extracted router."""

from fastapi import APIRouter, Query
from webapp.deps import get_cursor

router = APIRouter()

@router.get("/api/stats")
async def get_stats(structure_id: int | None = Query(None)):
    """Compteurs d'adresses par détection/validation pour une structure."""
    with get_cursor() as (cur, conn):
        # Résoudre la structure (défaut = UCA)
        if structure_id is None:
            cur.execute("SELECT id FROM structures WHERE code = 'uca'")
            row = cur.fetchone()
            structure_id = row["id"] if row else 0

        cur.execute("SELECT COUNT(*) AS total FROM addresses")
        total = cur.fetchone()["total"]

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE ast.matched_form_id IS NOT NULL) AS detected,
                COUNT(*) FILTER (WHERE ast.is_confirmed IS NULL) AS pending,
                COUNT(*) FILTER (WHERE ast.is_confirmed = FALSE) AS rejected,
                COUNT(*) FILTER (WHERE ast.is_confirmed = TRUE) AS confirmed
            FROM address_structures ast
            WHERE ast.structure_id = %s
        """, (structure_id,))
        row = cur.fetchone()

        return {
            "total": total,
            "detected": row["detected"],
            "pending": row["pending"],
            "rejected": row["rejected"],
            "confirmed": row["confirmed"],
        }


# ----- API: Structures CRUD -----











