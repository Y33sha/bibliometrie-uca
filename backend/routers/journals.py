"""Router Revues — liste, recherche, fusion."""

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.deps import get_cursor
from backend.models import JournalUpdate, MergeRequest
from services.journals import merge_journals
from services.journals import update_journal as _update_journal

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/journals")
async def list_journals(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    publisher_id: int | None = None,
    sort: str = "title",
):
    with get_cursor() as (cur, conn):
        conditions = []
        params = []

        if search and len(search) >= 2:
            conditions.append("j.title_normalized LIKE '%%' || %s || '%%'")
            params.append(search.lower())

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        where = " AND ".join(conditions) if conditions else "TRUE"

        # Count
        cur.execute(f"SELECT COUNT(*) FROM journals j WHERE {where}", params)
        total = cur.fetchone()["count"]

        # Sort
        sort_map = {
            "title": "j.title ASC",
            "-title": "j.title DESC",
            "publisher": "pub_name ASC NULLS LAST, j.title ASC",
            "-publisher": "pub_name DESC NULLS LAST, j.title ASC",
            "pubs": "pub_count ASC, j.title ASC",
            "-pubs": "pub_count DESC, j.title ASC",
        }
        order = sort_map.get(sort, sort_map["title"])

        offset = (page - 1) * per_page
        cur.execute(
            f"""
            SELECT j.id, j.title, j.issn, j.eissn, j.issnl,
                   j.publisher_id, p.name AS pub_name,
                   j.openalex_id, j.is_in_doaj, j.is_predatory,
                   j.apc_amount, j.apc_currency, j.oa_model,
                   j.journal_type, j.is_academic, j.doi_prefix, j.notes,
                   (SELECT COUNT(*) FROM publications pub
                    WHERE pub.journal_id = j.id) AS pub_count
            FROM journals j
            LEFT JOIN publishers p ON p.id = j.publisher_id
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "journals": cur.fetchall(),
        }


@router.put("/api/journals/{journal_id}")
@router.get("/api/journals/{journal_id}")
async def get_journal(journal_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id, title FROM journals WHERE id = %s", (journal_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Revue introuvable")
        return row


@router.put("/api/journals/{journal_id}")
async def update_journal(journal_id: int, body: JournalUpdate):
    """Met à jour une revue."""
    fields = body.model_dump(exclude_unset=True)
    with get_cursor() as (cur, conn):
        _update_journal(cur, journal_id, fields=fields)
        return {"ok": True}


@router.post("/api/journals/{journal_id}/merge")
async def merge(journal_id: int, body: MergeRequest):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM journals WHERE id IN (%s, %s)", (journal_id, body.source_id))
        found = {row["id"] for row in cur.fetchall()}
        if journal_id not in found:
            raise HTTPException(status_code=404, detail="Revue cible introuvable")
        if body.source_id not in found:
            raise HTTPException(status_code=404, detail="Revue source introuvable")

        merge_journals(cur, journal_id, body.source_id)
        return {"merged": True, "source_id": body.source_id, "target_id": journal_id}
