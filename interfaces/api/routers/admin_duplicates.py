"""Auto-extracted router."""

import logging

from fastapi import APIRouter, HTTPException, Query

from application.publications import mark_distinct as _mark_pubs_distinct
from application.publications import merge_publications
from interfaces.api.deps import get_cursor
from interfaces.api.models import MarkDistinctPublications, MergePublications

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/duplicates/next")
async def next_duplicate_candidate(
    min_title_len: int = Query(30, ge=10),
    offset: int = Query(0, ge=0),
):
    """Renvoie la paire candidate à la position offset."""
    with get_cursor() as (cur, conn):
        candidate_where = """
            FROM publications p1
            JOIN publications p2
              ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
            WHERE LENGTH(p1.title_normalized) > %s
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL AND LOWER(p1.doi) <> LOWER(p2.doi)
                       AND NOT (LOWER(p1.doi) LIKE '10.5281/zenodo.%%' AND LOWER(p2.doi) LIKE '10.5281/zenodo.%%'))
              AND NOT (
                  (p1.doc_type IN ('article', 'review') AND p2.doc_type = 'conference_paper')
                  OR (p2.doc_type IN ('article', 'review') AND p1.doc_type = 'conference_paper'))
              AND NOT (EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p1.id AND source = 'hal')
                       AND EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p2.id AND source = 'hal'))
              AND NOT (EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p1.id AND source = 'openalex')
                       AND EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p2.id AND source = 'openalex'))
              AND NOT (EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p1.id AND source = 'wos')
                       AND EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p2.id AND source = 'wos'))
              AND NOT EXISTS (
                  SELECT 1 FROM distinct_publications dp
                  WHERE dp.pub_id_a = LEAST(p1.id, p2.id) AND dp.pub_id_b = GREATEST(p1.id, p2.id))
        """

        # Compteur total
        cur.execute(
            f"SELECT COUNT(*) AS total FROM (SELECT p1.id {candidate_where}) sub", (min_title_len,)
        )
        total = cur.fetchone()["total"]

        # Paire à la position offset
        cur.execute(
            f"SELECT p1.id AS id_a, p2.id AS id_b {candidate_where} LIMIT 1 OFFSET %s",
            (min_title_len, offset),
        )
        row = cur.fetchone()

        if not row:
            return {"total": total, "offset": offset, "pair": None}

        def get_pub_detail(pub_id):
            cur.execute(
                """
                SELECT p.id, p.title, p.title_normalized, p.doi, p.pub_year,
                       p.doc_type::text, p.container_title, p.oa_status::text,
                       p.language, p.journal_id,
                       j.title AS journal_title, j.issn, j.eissn
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE p.id = %s
            """,
                (pub_id,),
            )
            pub = cur.fetchone()
            if not pub:
                return None

            sources = []
            cur.execute(
                "SELECT source, source_id FROM source_publications WHERE publication_id = %s",
                (pub_id,),
            )
            for r in cur.fetchall():
                sources.append({"source": r["source"], "source_id": r["source_id"]})

            cur.execute(
                """
                SELECT a.author_position, a.in_perimeter, a.person_id,
                       COALESCE(p2.last_name) AS last_name,
                       COALESCE(p2.first_name) AS first_name,
                       COALESCE(p2.last_name || ' ' || p2.first_name,
                                sa_hal.raw_author_name, sa_oa.raw_author_name, sa_wos.raw_author_name) AS full_name
                FROM authorships a
                LEFT JOIN persons p2 ON p2.id = a.person_id
                LEFT JOIN source_authorships sa_hal ON sa_hal.authorship_id = a.id AND sa_hal.source = 'hal'
                LEFT JOIN source_authorships sa_oa ON sa_oa.authorship_id = a.id AND sa_oa.source = 'openalex'
                LEFT JOIN source_authorships sa_wos ON sa_wos.authorship_id = a.id AND sa_wos.source = 'wos'
                WHERE a.publication_id = %s AND NOT a.excluded
                ORDER BY a.author_position NULLS LAST
            """,
                (pub_id,),
            )
            authors = [dict(r) for r in cur.fetchall()]

            return {
                "id": pub["id"],
                "title": pub["title"],
                "title_normalized": pub["title_normalized"],
                "doi": pub["doi"],
                "pub_year": pub["pub_year"],
                "doc_type": pub["doc_type"],
                "container_title": pub["container_title"],
                "oa_status": pub["oa_status"],
                "language": pub["language"],
                "journal": {
                    "id": pub["journal_id"],
                    "title": pub["journal_title"],
                    "issn": pub["issn"],
                    "eissn": pub["eissn"],
                }
                if pub["journal_id"]
                else None,
                "sources": sources,
                "authors": authors,
            }

        return {
            "total": total,
            "offset": offset,
            "pair": {
                "pub_a": get_pub_detail(row["id_a"]),
                "pub_b": get_pub_detail(row["id_b"]),
            },
        }


@router.post("/api/admin/duplicates/merge")
async def merge_duplicate_publications(body: MergePublications):
    """Fusionne source_id dans target_id."""
    if body.target_id == body.source_id:
        raise HTTPException(
            status_code=400, detail="target_id et source_id doivent être différents"
        )

    with get_cursor() as (cur, conn):
        cur.execute(
            "SELECT id, doi, journal_id, oa_status::text, language, container_title FROM publications WHERE id IN (%s, %s)",
            (body.target_id, body.source_id),
        )
        pubs = {r["id"]: r for r in cur.fetchall()}
        if body.target_id not in pubs or body.source_id not in pubs:
            raise HTTPException(status_code=404, detail="Publication introuvable")

        cur.execute("SAVEPOINT merge_dup")
        try:
            merge_publications(cur, body.target_id, body.source_id)
            cur.execute("RELEASE SAVEPOINT merge_dup")
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT merge_dup")
            raise HTTPException(status_code=500, detail=f"Échec de la fusion : {e}") from e

        return {"ok": True, "target_id": body.target_id, "source_id": body.source_id}


@router.post("/api/admin/duplicates/mark-distinct")
async def mark_publications_distinct(body: MarkDistinctPublications):
    """Marque deux publications comme distinctes (non-doublon)."""
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")
    with get_cursor() as (cur, conn):
        _mark_pubs_distinct(cur, body.pub_id_a, body.pub_id_b)
        return {"ok": True}


# ----- API: Adresses -----
