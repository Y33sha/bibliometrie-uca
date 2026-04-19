"""Query services pour les endpoints admin du router persons.

Couvre : orphan-authorships, name-form-authorships, hal-problems
(duplicate-accounts, duplicate-pubs-*, missing-collections, affiliation-conflicts).
"""

from typing import Any

from domain.sources import AUTHOR_SOURCES_SQL

# ── Orphan authorships ───────────────────────────────────────────

# Filtre commun : in_perimeter, sans person_id, sources principales,
# hors mémoires, hors personnes rejetées
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
    AND p.doc_type NOT IN ('memoir', 'peer_review')
    AND NOT EXISTS (
        SELECT 1 FROM source_authorships sa2
        JOIN persons pe ON pe.id = sa2.person_id AND pe.rejected = TRUE
        WHERE sa2.source_person_id = sa.source_person_id
    )
"""


def orphan_authorships_count(cur: Any) -> dict[str, Any]:
    """Nombre d'authorships UCA sans person_id."""
    cur.execute(f"""
        SELECT COUNT(*) AS total
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE {_ORPHAN_BASE}
    """)
    return cur.fetchone()


def list_orphan_authorships(cur: Any, *, search: str, page: int, per_page: int) -> dict[str, Any]:
    """Liste paginée des authorships orphelines avec publication."""
    offset = (page - 1) * per_page
    search_cond = ""
    params: list[Any] = []
    if search.strip():
        params.append(f"%{search.strip()}%")
        search_cond = "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(%s))"

    cur.execute(
        f"""
        SELECT COUNT(*) FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE {_ORPHAN_BASE}
          {search_cond}
        """,
        params,
    )
    total = cur.fetchone()["count"]

    cur.execute(
        f"""
        SELECT sa.source, sa.id AS authorship_id,
               sa.raw_author_name AS full_name,
               sd.publication_id,
               p.title AS pub_title, p.pub_year
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE {_ORPHAN_BASE}
          {search_cond}
        ORDER BY sa.raw_author_name, p.pub_year DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    return {
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page or 1,
        "authorships": cur.fetchall(),
    }


def person_exists(cur: Any, person_id: int) -> bool:
    """Vérifie qu'une personne existe."""
    cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
    return cur.fetchone() is not None


# ── Name-form authorships ────────────────────────────────────────


def name_form_authorships(cur: Any, person_id: int, name_form: str) -> dict[str, Any]:
    """Authorships sources liées à une personne pour une forme de nom donnée
    + autres personnes partageant cette forme."""
    cur.execute(
        f"""
        SELECT sa.source, sa.id AS authorship_id,
               sd.publication_id AS pub_id, sd.title, sd.pub_year, sd.doi
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.person_id = %s AND sa.author_name_normalized = %s
          AND sa.source IN {AUTHOR_SOURCES_SQL}
        ORDER BY sd.pub_year DESC, sd.title
        """,
        (person_id, name_form),
    )
    authorships = cur.fetchall()

    cur.execute(
        """
        SELECT p.id, p.first_name, p.last_name,
               pr.department_name,
               EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh
        FROM person_name_forms pnf,
             LATERAL unnest(pnf.person_ids) AS pid
        JOIN persons p ON p.id = pid
        LEFT JOIN persons_rh pr ON pr.person_id = p.id
        WHERE pnf.name_form = %s
          AND pid <> %s
          AND p.rejected = FALSE
        ORDER BY p.last_name, p.first_name
        """,
        (name_form, person_id),
    )
    other_persons = cur.fetchall()
    return {"authorships": authorships, "other_persons": other_persons}


def name_form_remaining_authorships(cur: Any, person_id: int, name_form: str) -> int:
    """Compte les authorships qui restent liées à une personne pour un name_form."""
    cur.execute(
        f"""
        SELECT COUNT(*) FROM source_authorships sa
        WHERE sa.person_id = %s AND sa.author_name_normalized = %s
          AND sa.source IN {AUTHOR_SOURCES_SQL}
        """,
        (person_id, name_form),
    )
    return cur.fetchone()["count"]


# ── HAL duplicate accounts ───────────────────────────────────────


def hal_duplicate_accounts(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Personnes liées à 2+ comptes HAL distincts."""
    offset = (page - 1) * per_page
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT person_id
            FROM source_persons
            WHERE source = 'hal' AND person_id IS NOT NULL
              AND (source_ids->>'hal_person_id') IS NOT NULL
            GROUP BY person_id
            HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
        ) sub
    """)
    total = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT p.id AS person_id, p.last_name, p.first_name,
               (prh.id IS NOT NULL) AS has_rh,
               (SELECT json_agg(json_build_object(
                   'hal_person_id', (sa.source_ids->>'hal_person_id')::int,
                   'full_name', sa.full_name,
                   'idhal', sa.source_ids->>'idhal',
                   'orcid', sa.orcid,
                   'pub_count', (SELECT COUNT(*) FROM source_authorships sa2
                                 WHERE sa2.source = 'hal' AND sa2.source_person_id = sa.id)
               ) ORDER BY (sa.source_ids->>'hal_person_id')::int)
                FROM source_persons sa
                WHERE sa.source = 'hal' AND sa.person_id = p.id
                  AND (sa.source_ids->>'hal_person_id') IS NOT NULL
               ) AS hal_accounts
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id IN (
            SELECT person_id
            FROM source_persons
            WHERE source = 'hal' AND person_id IS NOT NULL
              AND (source_ids->>'hal_person_id') IS NOT NULL
            GROUP BY person_id
            HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
        )
        ORDER BY LOWER(p.last_name), LOWER(p.first_name)
        LIMIT %s OFFSET %s
        """,
        (per_page, offset),
    )
    persons = [dict(r) for r in cur.fetchall()]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "persons": persons,
    }


# ── HAL duplicate publications ───────────────────────────────────


def _hal_pub_detail(cur: Any, pub_id: int) -> dict[str, Any] | None:
    """Détail publication pour doublons HAL."""
    cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doc_type::text, p.doi, p.container_title
        FROM publications p WHERE p.id = %s
        """,
        (pub_id,),
    )
    pub = cur.fetchone()
    if not pub:
        return None
    cur.execute(
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
    hal_docs = [dict(r) for r in cur.fetchall()]
    return {**dict(pub), "hal_docs": hal_docs}


def hal_duplicate_pubs_by_doi(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    offset = (page - 1) * per_page
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT sd.publication_id, LOWER(sd.doi)
            FROM source_publications sd
            WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
            GROUP BY sd.publication_id, LOWER(sd.doi)
            HAVING COUNT(*) >= 2
        ) sub
    """)
    total = cur.fetchone()["count"]

    cur.execute(
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
    pairs = []
    for r in cur.fetchall():
        pub = _hal_pub_detail(cur, r["pub_id"])
        if pub:
            pairs.append({"doi": r["doi"], "halids": r["halids"], "publication": pub})

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "pairs": pairs,
    }


def hal_duplicate_pubs_by_metadata(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
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

    cur.execute(f"SELECT COUNT(*) {dup_query}")
    total = cur.fetchone()["count"]

    cur.execute(
        f"""
        SELECT p1.id AS id_a, p2.id AS id_b
        {dup_query}
        ORDER BY p1.id
        LIMIT %s OFFSET %s
        """,
        (per_page, offset),
    )
    pairs = []
    for r in cur.fetchall():
        pub_a = _hal_pub_detail(cur, r["id_a"])
        pub_b = _hal_pub_detail(cur, r["id_b"])
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


def hal_missing_collections_labs(cur: Any) -> list[dict[str, Any]]:
    """Liste des labos avec collection HAL configurée."""
    cur.execute("""
        SELECT s.id, s.acronym, s.name, s.hal_collection
        FROM structures s
        WHERE s.hal_collection IS NOT NULL AND s.structure_type = 'labo'
        ORDER BY s.acronym
    """)
    return [dict(r) for r in cur.fetchall()]


def hal_missing_collections(cur: Any, *, lab_id: int, page: int, per_page: int) -> dict[str, Any]:
    """Publications affiliées à un labo sur OA/WoS, présentes dans HAL,
    mais absentes de la collection HAL du labo."""
    cur.execute("SELECT acronym, hal_collection FROM structures WHERE id = %s", (lab_id,))
    lab = cur.fetchone()
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

    cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}", params)
    total = cur.fetchone()["count"]

    cur.execute(
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
    pubs = [dict(r) for r in cur.fetchall()]

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


def hal_affiliation_conflicts(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Publications affiliées UCA dans HAL mais pas dans OA/WoS."""
    cur.execute("SET LOCAL jit = off")
    offset = (page - 1) * per_page
    base_where = """
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        WHERE a.in_perimeter = TRUE
          AND EXISTS (SELECT 1 FROM source_authorships sa
                      WHERE sa.authorship_id = a.id AND sa.source = 'hal')
          AND EXISTS (SELECT 1 FROM structures s
                      WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo')
          AND (
              EXISTS (
                  SELECT 1 FROM source_authorships sa
                  JOIN source_publications sd ON sd.id = sa.source_publication_id
                  WHERE sd.publication_id = p.id
                    AND sa.source = 'openalex'
                    AND sa.author_position = a.author_position
                    AND sa.in_perimeter = FALSE
                    AND EXISTS (SELECT 1 FROM source_authorship_addresses saa
                                WHERE saa.source_authorship_id = sa.id)
              )
              OR EXISTS (
                  SELECT 1 FROM source_authorships sa
                  JOIN source_publications sd ON sd.id = sa.source_publication_id
                  WHERE sd.publication_id = p.id
                    AND sa.source = 'wos'
                    AND sa.author_position = a.author_position
                    AND sa.in_perimeter = FALSE
                    AND EXISTS (SELECT 1 FROM source_authorship_addresses saa
                                WHERE saa.source_authorship_id = sa.id)
              )
          )
    """

    cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}")
    total = cur.fetchone()["count"]

    cur.execute(
        f"""
        SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
               (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
               (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                FROM structures s
                WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo') AS labs
        {base_where}
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
        for r in cur.fetchall()
    ]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "publications": pubs,
    }
