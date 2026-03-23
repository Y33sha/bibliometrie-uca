"""Auto-extracted router."""

from fastapi import APIRouter, Query, HTTPException
from webapp.deps import get_cursor

router = APIRouter()

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
              AND NOT (EXISTS (SELECT 1 FROM hal_documents WHERE publication_id = p1.id)
                       AND EXISTS (SELECT 1 FROM hal_documents WHERE publication_id = p2.id))
              AND NOT (EXISTS (SELECT 1 FROM openalex_documents WHERE publication_id = p1.id)
                       AND EXISTS (SELECT 1 FROM openalex_documents WHERE publication_id = p2.id))
              AND NOT (EXISTS (SELECT 1 FROM wos_documents WHERE publication_id = p1.id)
                       AND EXISTS (SELECT 1 FROM wos_documents WHERE publication_id = p2.id))
              AND NOT EXISTS (
                  SELECT 1 FROM distinct_publications dp
                  WHERE dp.pub_id_a = LEAST(p1.id, p2.id) AND dp.pub_id_b = GREATEST(p1.id, p2.id))
        """

        # Compteur total
        cur.execute(f"SELECT COUNT(*) AS total FROM (SELECT p1.id {candidate_where}) sub",
                    (min_title_len,))
        total = cur.fetchone()["total"]

        # Paire à la position offset
        cur.execute(f"SELECT p1.id AS id_a, p2.id AS id_b {candidate_where} LIMIT 1 OFFSET %s",
                    (min_title_len, offset))
        row = cur.fetchone()

        if not row:
            return {"total": total, "offset": offset, "pair": None}

        def get_pub_detail(pub_id):
            cur.execute("""
                SELECT p.id, p.title, p.title_normalized, p.doi, p.pub_year,
                       p.doc_type::text, p.container_title, p.oa_status::text,
                       p.language, p.journal_id,
                       j.title AS journal_title, j.issn, j.eissn
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE p.id = %s
            """, (pub_id,))
            pub = cur.fetchone()
            if not pub:
                return None

            sources = []
            cur.execute("SELECT halid AS source_id FROM hal_documents WHERE publication_id = %s", (pub_id,))
            for r in cur.fetchall():
                sources.append({"source": "hal", "source_id": r["source_id"]})
            cur.execute("SELECT openalex_id AS source_id FROM openalex_documents WHERE publication_id = %s", (pub_id,))
            for r in cur.fetchall():
                sources.append({"source": "openalex", "source_id": r["source_id"]})
            cur.execute("SELECT ut AS source_id FROM wos_documents WHERE publication_id = %s", (pub_id,))
            for r in cur.fetchall():
                sources.append({"source": "wos", "source_id": r["source_id"]})

            cur.execute("""
                SELECT a.author_position, a.is_uca, a.person_id,
                       COALESCE(p2.last_name,
                                ha.last_name, oa.last_name, wa.last_name) AS last_name,
                       COALESCE(p2.first_name,
                                ha.first_name, oa.first_name, wa.first_name) AS first_name,
                       COALESCE(p2.last_name || ' ' || p2.first_name,
                                ha.full_name, oas.raw_author_name, oa.full_name, wa.full_name) AS full_name
                FROM authorships a
                LEFT JOIN persons p2 ON p2.id = a.person_id
                LEFT JOIN hal_authorships has2 ON has2.id = a.hal_authorship_id
                LEFT JOIN hal_authors ha ON ha.id = has2.hal_author_id
                LEFT JOIN openalex_authorships oas ON oas.id = a.openalex_authorship_id
                LEFT JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
                LEFT JOIN wos_authorships was2 ON was2.id = a.wos_authorship_id
                LEFT JOIN wos_authors wa ON wa.id = was2.wos_author_id
                WHERE a.publication_id = %s AND NOT a.excluded
                ORDER BY a.author_position NULLS LAST
            """, (pub_id,))
            authors = [dict(r) for r in cur.fetchall()]

            return {
                "id": pub["id"], "title": pub["title"],
                "title_normalized": pub["title_normalized"],
                "doi": pub["doi"], "pub_year": pub["pub_year"],
                "doc_type": pub["doc_type"],
                "container_title": pub["container_title"],
                "oa_status": pub["oa_status"], "language": pub["language"],
                "journal": {"id": pub["journal_id"], "title": pub["journal_title"],
                            "issn": pub["issn"], "eissn": pub["eissn"]}
                           if pub["journal_id"] else None,
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
async def merge_duplicate_publications(body: dict):
    """Fusionne source_id dans target_id."""
    target_id = body.get("target_id")
    source_id = body.get("source_id")
    if not target_id or not source_id or target_id == source_id:
        raise HTTPException(status_code=400, detail="target_id et source_id requis et différents")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id, doi, journal_id, oa_status::text, language, container_title FROM publications WHERE id IN (%s, %s)", (target_id, source_id))
        pubs = {r["id"]: r for r in cur.fetchall()}
        if target_id not in pubs or source_id not in pubs:
            raise HTTPException(status_code=404, detail="Publication introuvable")

        cur.execute("SAVEPOINT merge_dup")
        try:
            for tbl in ("hal_documents", "openalex_documents", "wos_documents"):
                cur.execute(f"UPDATE {tbl} SET publication_id = %s WHERE publication_id = %s",
                            (target_id, source_id))

            cur.execute("""
                DELETE FROM authorships
                WHERE publication_id = %s
                  AND person_id IN (
                      SELECT person_id FROM authorships WHERE publication_id = %s
                  )
            """, (source_id, target_id))

            cur.execute("UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
                        (target_id, source_id))

            cur.execute("""
                UPDATE publications dest SET
                    doi = CASE
                        WHEN dest.doi IS NOT NULL THEN dest.doi
                        WHEN src.doi IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM publications p2
                            WHERE LOWER(p2.doi) = LOWER(src.doi) AND p2.id <> dest.id
                        ) THEN LOWER(src.doi)
                        ELSE dest.doi END,
                    journal_id = COALESCE(dest.journal_id, src.journal_id),
                    oa_status = CASE
                        WHEN src.oa_status = 'diamond' THEN 'diamond'
                        WHEN dest.oa_status IN ('unknown', 'closed') AND src.oa_status NOT IN ('unknown', 'closed')
                        THEN src.oa_status ELSE dest.oa_status END,
                    language = COALESCE(dest.language, src.language),
                    container_title = COALESCE(dest.container_title, src.container_title),
                    countries = CASE
                        WHEN dest.countries IS NULL THEN src.countries
                        WHEN src.countries IS NULL THEN dest.countries
                        ELSE (SELECT array_agg(DISTINCT c ORDER BY c) FROM unnest(dest.countries || src.countries) AS c)
                        END,
                    updated_at = now()
                FROM publications src
                WHERE dest.id = %s AND src.id = %s
            """, (target_id, source_id))

            cur.execute("DELETE FROM distinct_publications WHERE pub_id_a = %s OR pub_id_b = %s OR pub_id_a = %s OR pub_id_b = %s",
                        (source_id, source_id, source_id, source_id))

            cur.execute("DELETE FROM publications WHERE id = %s", (source_id,))

            cur.execute("RELEASE SAVEPOINT merge_dup")
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT merge_dup")
            raise HTTPException(status_code=500, detail=f"Échec de la fusion : {e}")

        return {"ok": True, "target_id": target_id, "source_id": source_id}


@router.post("/api/admin/duplicates/mark-distinct")
async def mark_publications_distinct(body: dict):
    """Marque deux publications comme distinctes (non-doublon)."""
    a = body.get("pub_id_a")
    b = body.get("pub_id_b")
    if not a or not b or a == b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b requis et différents")

    with get_cursor() as (cur, conn):
        cur.execute("""
            INSERT INTO distinct_publications (pub_id_a, pub_id_b)
            VALUES (LEAST(%s, %s), GREATEST(%s, %s))
            ON CONFLICT DO NOTHING
        """, (a, b, a, b))
        return {"ok": True}


# ----- API: Adresses -----

