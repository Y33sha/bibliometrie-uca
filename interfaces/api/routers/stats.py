"""Auto-extracted router."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from interfaces.api.deps import get_cursor

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/address-stats")
async def get_stats(structure_id: int | None = Query(None)) -> Any:
    """Compteurs d'adresses par détection/validation pour une structure."""
    with get_cursor() as (cur, conn):
        # Résoudre la structure (défaut = première racine du périmètre)
        if structure_id is None:
            from infrastructure.app_config import _get_from_db

            perim_code = _get_from_db(cur, "perimeter_persons") or "uca"
            cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (perim_code,))
            row = cur.fetchone()
            root_ids = (row["structure_ids"] if isinstance(row, dict) else row[0]) if row else []
            structure_id = root_ids[0] if root_ids else 0

        cur.execute("SELECT COUNT(*) AS total FROM addresses")
        total = cur.fetchone()["total"]

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE ast.matched_form_id IS NOT NULL) AS detected,
                COUNT(*) FILTER (WHERE ast.is_confirmed IS NULL) AS pending,
                COUNT(*) FILTER (WHERE ast.is_confirmed = FALSE) AS rejected,
                COUNT(*) FILTER (WHERE ast.is_confirmed = TRUE) AS confirmed
            FROM address_structures ast
            WHERE ast.structure_id = %s
        """,
            (structure_id,),
        )
        row = cur.fetchone()

        return {
            "total": total,
            "detected": row["detected"],
            "pending": row["pending"],
            "rejected": row["rejected"],
            "confirmed": row["confirmed"],
        }


# ----- API: Structures CRUD -----
