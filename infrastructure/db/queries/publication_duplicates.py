"""Query services async pour /api/admin/duplicates/* (§2.12)."""

from typing import Any

_PUB_CANDIDATE_WHERE = """
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


async def _get_pub_detail(cur: Any, pub_id: int) -> dict[str, Any] | None:
    """Détail d'une publication pour la page de déduplication."""
    await cur.execute(
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
    pub = await cur.fetchone()
    if not pub:
        return None

    await cur.execute(
        "SELECT source, source_id FROM source_publications WHERE publication_id = %s",
        (pub_id,),
    )
    sources = [{"source": r["source"], "source_id": r["source_id"]} for r in await cur.fetchall()]

    await cur.execute(
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
    authors = [dict(r) for r in await cur.fetchall()]

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


async def next_pub_duplicate(cur: Any, *, min_title_len: int, offset: int) -> dict[str, Any]:
    """Renvoie la paire candidate doublon-publications à la position offset."""
    await cur.execute(
        f"SELECT COUNT(*) AS total FROM (SELECT p1.id {_PUB_CANDIDATE_WHERE}) sub",
        (min_title_len,),
    )
    row = await cur.fetchone()
    total = row["total"]

    await cur.execute(
        f"SELECT p1.id AS id_a, p2.id AS id_b {_PUB_CANDIDATE_WHERE} LIMIT 1 OFFSET %s",
        (min_title_len, offset),
    )
    row = await cur.fetchone()
    if not row:
        return {"total": total, "offset": offset, "pair": None}

    return {
        "total": total,
        "offset": offset,
        "pair": {
            "pub_a": await _get_pub_detail(cur, row["id_a"]),
            "pub_b": await _get_pub_detail(cur, row["id_b"]),
        },
    }


async def get_publications_basic(cur: Any, pub_ids: list[int]) -> dict[int, Any]:
    """Résout un lot de publications (existence check + métadonnées de base)."""
    await cur.execute(
        "SELECT id, doi, journal_id, oa_status::text, language, container_title "
        "FROM publications WHERE id = ANY(%s)",
        (list(pub_ids),),
    )
    return {r["id"]: r for r in await cur.fetchall()}
