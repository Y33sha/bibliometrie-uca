"""Router Éditeurs — liste, recherche, fusion."""

from fastapi import APIRouter, HTTPException, Query
from backend.deps import get_cursor
from services.journals import merge_publishers

router = APIRouter()


@router.get("/api/publishers")
async def list_publishers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    sort: str = "name",
):
    with get_cursor() as (cur, conn):
        conditions = []
        params = []

        if search and len(search) >= 2:
            conditions.append("p.name_normalized LIKE '%%' || %s || '%%'")
            params.append(search.lower())

        where = " AND ".join(conditions) if conditions else "TRUE"

        # Count
        cur.execute(f"SELECT COUNT(*) FROM publishers p WHERE {where}", params)
        total = cur.fetchone()["count"]

        # Sort
        sort_map = {
            "name": "p.name ASC",
            "-name": "p.name DESC",
            "journals": "journal_count ASC, p.name ASC",
            "-journals": "journal_count DESC, p.name ASC",
            "pubs": "pub_count ASC, p.name ASC",
            "-pubs": "pub_count DESC, p.name ASC",
        }
        order = sort_map.get(sort, sort_map["name"])

        offset = (page - 1) * per_page
        cur.execute(f"""
            SELECT p.id, p.name, p.openalex_id, p.country,
                   p.is_predatory,
                   (SELECT COUNT(*) FROM journals j WHERE j.publisher_id = p.id) AS journal_count,
                   (SELECT COUNT(*) FROM publications pub
                    JOIN journals j2 ON j2.id = pub.journal_id
                    WHERE j2.publisher_id = p.id) AS pub_count
            FROM publishers p
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "publishers": cur.fetchall(),
        }


@router.post("/api/publishers/{publisher_id}/merge")
async def merge(publisher_id: int, body: dict):
    source_id = body.get("source_id")
    if not source_id or source_id == publisher_id:
        raise HTTPException(status_code=400, detail="source_id invalide")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM publishers WHERE id IN (%s, %s)",
                    (publisher_id, source_id))
        found = {row["id"] for row in cur.fetchall()}
        if publisher_id not in found:
            raise HTTPException(status_code=404, detail="Éditeur cible introuvable")
        if source_id not in found:
            raise HTTPException(status_code=404, detail="Éditeur source introuvable")

        try:
            merge_publishers(cur, publisher_id, source_id)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))

        return {"merged": True, "source_id": source_id, "target_id": publisher_id}
