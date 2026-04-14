"""Router Revues — liste, recherche, fusion."""

from fastapi import APIRouter, HTTPException, Query
from backend.deps import get_cursor
from services.journals import merge_journals

router = APIRouter()


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
        cur.execute(f"""
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
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "journals": cur.fetchall(),
        }


@router.put("/api/journals/{journal_id}")
async def update_journal(journal_id: int, body: dict):
    """Met à jour une revue."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM journals WHERE id = %s", (journal_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Revue introuvable")

        fields = {}
        for key in ("title", "issn", "eissn", "issnl", "doi_prefix",
                     "oa_model", "journal_type", "is_academic",
                     "is_predatory", "is_in_doaj", "apc_amount", "notes"):
            if key in body:
                fields[key] = body[key]
        if "title" in fields:
            from utils.normalize import normalize_text
            fields["title_normalized"] = normalize_text(fields["title"])

        if not fields:
            raise HTTPException(status_code=400, detail="Rien à modifier")

        sets = ", ".join(f"{k} = %s" for k in fields)
        cur.execute(
            f"UPDATE journals SET {sets}, updated_at = now() WHERE id = %s",
            list(fields.values()) + [journal_id])
        return {"ok": True}


@router.post("/api/journals/{journal_id}/merge")
async def merge(journal_id: int, body: dict):
    source_id = body.get("source_id")
    if not source_id or source_id == journal_id:
        raise HTTPException(status_code=400, detail="source_id invalide")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM journals WHERE id IN (%s, %s)",
                    (journal_id, source_id))
        found = {row["id"] for row in cur.fetchall()}
        if journal_id not in found:
            raise HTTPException(status_code=404, detail="Revue cible introuvable")
        if source_id not in found:
            raise HTTPException(status_code=404, detail="Revue source introuvable")

        try:
            merge_journals(cur, journal_id, source_id)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))

        return {"merged": True, "source_id": source_id, "target_id": journal_id}
