"""Query services async pour le router `/api/hal-problems/*` (§2.12).

Contrôles qualité HAL au niveau des publications (doublons de dépôts,
manques dans les collections, conflits d'affiliation).
"""

from typing import Any


async def _hal_pub_detail(cur: Any, pub_id: int) -> dict[str, Any] | None:
    """Détail publication pour doublons HAL."""
    await cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doc_type::text, p.doi, p.container_title
        FROM publications p WHERE p.id = %s
        """,
        (pub_id,),
    )
    pub = await cur.fetchone()
    if not pub:
        return None
    await cur.execute(
        """
        SELECT sd.source_id AS halid, sd.hal_collections, sd.doc_type AS hal_doc_type,
               sd.pub_year AS hal_pub_year, sd.title AS hal_title,
               (SELECT COUNT(*) FROM source_authorships sa2
                WHERE sa2.source = 'hal' AND sa2.source_publication_id = sd.id
                  AND NOT sa2.excluded) AS author_count
        FROM source_publications sd WHERE sd.publication_id = %s AND sd.source = 'hal'
        """,
        (pub_id,),
    )
    hal_docs = [dict(r) for r in await cur.fetchall()]
    return {**dict(pub), "hal_docs": hal_docs}


async def hal_duplicate_pubs_by_doi(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    offset = (page - 1) * per_page
    await cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT sd.publication_id, LOWER(sd.doi)
            FROM source_publications sd
            WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
            GROUP BY sd.publication_id, LOWER(sd.doi)
            HAVING COUNT(*) >= 2
        ) sub
    """)
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        """
        SELECT LOWER(sd.doi) AS doi,
               sd.publication_id AS pub_id,
               array_agg(sd.source_id ORDER BY sd.source_id) AS halids
        FROM source_publications sd
        WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
        GROUP BY sd.publication_id, LOWER(sd.doi)
        HAVING COUNT(*) >= 2
        ORDER BY LOWER(sd.doi)
        LIMIT %s OFFSET %s
        """,
        (per_page, offset),
    )
    rows = await cur.fetchall()
    pairs = []
    for r in rows:
        pub = await _hal_pub_detail(cur, r["pub_id"])
        if pub:
            pairs.append({"doi": r["doi"], "halids": r["halids"], "publication": pub})

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "pairs": pairs,
    }


async def hal_duplicate_pubs_by_metadata(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Doublons possibles : dépôts HAL avec métadonnées identiques."""
    offset = (page - 1) * per_page
    dup_query = """
        FROM publications p1
        JOIN publications p2 ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
        JOIN source_publications hd1 ON hd1.publication_id = p1.id AND hd1.source = 'hal'
        JOIN source_publications hd2 ON hd2.publication_id = p2.id AND hd2.source = 'hal'
        WHERE LENGTH(p1.title_normalized) > 30
          AND p1.pub_year = p2.pub_year
          AND p1.doc_type = p2.doc_type
          AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL AND LOWER(p1.doi) <> LOWER(p2.doi))
          AND ABS(
              (SELECT COUNT(*) FROM source_authorships sa1
               WHERE sa1.source = 'hal' AND sa1.source_publication_id = hd1.id AND NOT sa1.excluded)
              - (SELECT COUNT(*) FROM source_authorships sa2
                 WHERE sa2.source = 'hal' AND sa2.source_publication_id = hd2.id AND NOT sa2.excluded)
          ) <= 2
          AND NOT EXISTS (SELECT 1 FROM distinct_publications dp
                          WHERE dp.pub_id_a = LEAST(p1.id, p2.id) AND dp.pub_id_b = GREATEST(p1.id, p2.id))
    """

    await cur.execute(f"SELECT COUNT(*) {dup_query}")
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        f"""
        SELECT p1.id AS id_a, p2.id AS id_b
        {dup_query}
        ORDER BY p1.id
        LIMIT %s OFFSET %s
        """,
        (per_page, offset),
    )
    rows = await cur.fetchall()
    pairs = []
    for r in rows:
        pub_a = await _hal_pub_detail(cur, r["id_a"])
        pub_b = await _hal_pub_detail(cur, r["id_b"])
        if pub_a and pub_b:
            pairs.append({"pub_a": pub_a, "pub_b": pub_b})

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "pairs": pairs,
    }


# ── HAL missing collections ──────────────────────────────────────


async def hal_missing_collections_labs(cur: Any) -> list[dict[str, Any]]:
    """Liste des labos avec collection HAL configurée."""
    await cur.execute("""
        SELECT s.id, s.acronym, s.name, s.hal_collection
        FROM structures s
        WHERE s.hal_collection IS NOT NULL AND s.structure_type = 'labo'
        ORDER BY s.acronym
    """)
    return [dict(r) for r in await cur.fetchall()]


async def hal_missing_collections(
    cur: Any, *, lab_id: int, page: int, per_page: int
) -> dict[str, Any]:
    """Publications affiliées à un labo sur OA/WoS, présentes dans HAL,
    mais absentes de la collection HAL du labo."""
    await cur.execute("SELECT acronym, hal_collection FROM structures WHERE id = %s", (lab_id,))
    lab = await cur.fetchone()
    if not lab or not lab["hal_collection"]:
        return {"error": "no_collection"}

    offset = (page - 1) * per_page
    col = lab["hal_collection"]
    lab_arr = [lab_id]

    base_where = """
        FROM publications p
        JOIN authorships a ON a.publication_id = p.id AND a.structure_ids && %s::int[]
        WHERE EXISTS (SELECT 1 FROM source_publications sd
                      WHERE sd.publication_id = p.id AND sd.source = 'hal')
          AND NOT EXISTS (SELECT 1 FROM source_publications sd
                          WHERE sd.publication_id = p.id AND sd.source = 'hal'
                            AND %s = ANY(sd.hal_collections))
    """
    params: list[Any] = [lab_arr, col]

    await cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}", params)
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        f"""
        SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
               (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
               NOT EXISTS (SELECT 1 FROM source_publications sd2
                           WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
                             AND 'PRES_CLERMONT' = ANY(sd2.hal_collections)) AS hors_uca
        {base_where}
        ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    pubs = [dict(r) for r in await cur.fetchall()]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "lab_acronym": lab["acronym"],
        "hal_collection": col,
        "publications": pubs,
    }


# ── HAL affiliation conflicts ────────────────────────────────────


async def hal_affiliation_conflicts(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Publications affiliées UCA dans HAL mais pas dans OA/WoS."""
    offset = (page - 1) * per_page
    # CTE en 3 passes :
    # 1. `hal_uca`     : authorships UCA attestés HAL + rattachés à un labo.
    # 2. `conflicting` : source_authorships OA/WoS hors-UCA avec adresse
    #                    (preuve que la source a bien examiné l'affiliation).
    # 3. `conflict_pubs` : publications où HAL-UCA et OA/WoS-hors-UCA
    #                     coexistent à la MÊME position d'auteur.
    # Remplace les EXISTS corrélés imbriqués (ré-évalués à chaque ligne de
    # `authorships`) par des scans hachés évalués une seule fois.
    base_cte = """
    WITH hal_uca AS (
        SELECT a.publication_id, a.author_position
        FROM authorships a
        WHERE a.in_perimeter = TRUE
          AND EXISTS (SELECT 1 FROM source_authorships sa
                      WHERE sa.authorship_id = a.id AND sa.source = 'hal')
          AND EXISTS (SELECT 1 FROM structures s
                      WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo')
    ),
    conflicting AS (
        SELECT DISTINCT sd.publication_id, sa.author_position
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.source IN ('openalex', 'wos')
          AND sa.in_perimeter = FALSE
          AND EXISTS (SELECT 1 FROM source_authorship_addresses saa
                      WHERE saa.source_authorship_id = sa.id)
    ),
    conflict_pubs AS (
        SELECT DISTINCT h.publication_id
        FROM hal_uca h
        JOIN conflicting c
          ON c.publication_id = h.publication_id
         AND c.author_position = h.author_position
    )
    """

    await cur.execute(f"{base_cte} SELECT COUNT(*) AS n FROM conflict_pubs")
    row = await cur.fetchone()
    total = row["n"]

    await cur.execute(
        f"""
        {base_cte}
        SELECT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
               (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
               (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                FROM authorships a2
                JOIN structures s ON s.id = ANY(a2.structure_ids)
                WHERE a2.publication_id = p.id
                  AND a2.in_perimeter = TRUE
                  AND s.structure_type = 'labo') AS labs
        FROM conflict_pubs cp
        JOIN publications p ON p.id = cp.publication_id
        ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
        LIMIT %s OFFSET %s
        """,
        (per_page, offset),
    )
    pubs = [
        {
            "id": r["id"],
            "title": r["title"],
            "pub_year": r["pub_year"],
            "doc_type": r["doc_type"],
            "doi": r["doi"],
            "halids": r["halids"],
            "labs": r["labs"],
        }
        for r in await cur.fetchall()
    ]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "publications": pubs,
    }
