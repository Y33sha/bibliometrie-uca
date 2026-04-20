"""Détail d'une personne : profil, auteurs liés, thèses encadrées, adresses."""

from typing import Any


def get_person(cur: Any, person_id: int) -> dict[str, Any] | None:
    """Détail d'une personne avec auteurs liés (admin)."""
    cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
            p.last_name_normalized, p.first_name_normalized,
            prh.role_title, prh.department_name, prh.start_date, prh.end_date,
            (prh.id IS NOT NULL) AS has_rh,
            (SELECT json_agg(x) FROM (
                SELECT DISTINCT ON (sa.source, sa.source_person_id)
                       sa.source_person_id AS id, sa.source,
                       sa.raw_author_name AS full_name
                FROM source_authorships sa
                WHERE sa.person_id = p.id AND NOT sa.excluded
                ORDER BY sa.source, sa.source_person_id
            ) x) AS linked_authors,
            (SELECT json_agg(json_build_object(
                'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                'source', pi.source, 'status', pi.status
            ) ORDER BY pi.id_type, pi.id_value) FROM person_identifiers pi WHERE pi.person_id = p.id
            ) AS identifiers
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
        """,
        (person_id,),
    )
    return cur.fetchone()


def person_profile(cur: Any, person_id: int) -> dict[str, Any] | None:
    """Profil public : infos + identifiants + auteurs liés."""
    cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
               prh.role_title, prh.department_name,
               prh.start_date, prh.end_date
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
        """,
        (person_id,),
    )
    person = cur.fetchone()
    if not person:
        return None

    cur.execute(
        """
        SELECT id, id_type, id_value, source, status
        FROM person_identifiers WHERE person_id = %s
        """,
        (person_id,),
    )
    identifiers = cur.fetchall()

    cur.execute(
        """
        SELECT DISTINCT sauth.id, 'hal' AS source, sauth.full_name, sauth.orcid,
               sauth.source_ids->>'idhal' AS idhal,
               (sauth.source_ids->>'hal_person_id')::int AS hal_person_id,
               NULL::text AS openalex_id,
               (SELECT COUNT(*) FROM source_authorships sa2
                WHERE sa2.source = 'hal' AND sa2.source_person_id = sauth.id
                  AND sa2.in_perimeter = TRUE AND NOT sa2.excluded) AS uca_pub_count
        FROM source_persons sauth
        JOIN source_authorships sa ON sa.source = 'hal' AND sa.source_person_id = sauth.id
        WHERE sa.person_id = %s AND NOT sa.excluded
        """,
        (person_id,),
    )
    hal_authors = cur.fetchall()

    cur.execute(
        """
        SELECT MIN(sa.id) AS id,
               sa.raw_author_name AS full_name,
               'openalex' AS source,
               NULL::text AS orcid, NULL::text AS idhal, NULL::text AS openalex_id,
               COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS uca_pub_count
        FROM source_authorships sa
        WHERE sa.source = 'openalex' AND sa.person_id = %s
        GROUP BY sa.raw_author_name
        """,
        (person_id,),
    )
    oa_authors = cur.fetchall()

    cur.execute(
        """
        SELECT sauth.id, 'wos' AS source, sa.raw_author_name AS full_name, sauth.orcid,
               NULL::text AS idhal, NULL::text AS openalex_id,
               (SELECT COUNT(*) FROM source_authorships sa2
                WHERE sa2.source = 'wos' AND sa2.source_person_id = sauth.id
                  AND sa2.in_perimeter = TRUE) AS uca_pub_count
        FROM source_persons sauth
        JOIN source_authorships sa ON sa.source = 'wos' AND sa.source_person_id = sauth.id
        WHERE sa.person_id = %s
        GROUP BY sauth.id, sa.raw_author_name, sauth.orcid
        """,
        (person_id,),
    )
    wos_authors = cur.fetchall()

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.person_id = %s
          AND sa.source = 'theses'
          AND NOT (sa.roles && ARRAY['author']::text[])
          AND sd.publication_id IS NOT NULL
        """,
        (person_id,),
    )
    theses_count = cur.fetchone()["count"]

    return {
        "person": person,
        "identifiers": identifiers,
        "authors": hal_authors + oa_authors + wos_authors,
        "theses_count": theses_count,
    }


# ── Thèses encadrées ─────────────────────────────────────────────


_THESIS_ROLES = ("thesis_director", "rapporteur", "jury_president", "jury_member")
_THESIS_ROLE_LABELS = {
    "thesis_director": "Directeur/directrice de thèse",
    "rapporteur": "Rapporteur",
    "jury_president": "Président du jury",
    "jury_member": "Membre du jury",
}


def person_theses(cur: Any, person_id: int) -> dict[str, Any]:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doi,
               sa.roles,
               (SELECT sa2.raw_author_name
                FROM source_authorships sa2
                WHERE sa2.source_publication_id = sd.id
                  AND sa2.source = 'theses'
                  AND sa2.roles && ARRAY['author']::text[]
                LIMIT 1
               ) AS author_name,
               (SELECT sa2.person_id
                FROM source_authorships sa2
                WHERE sa2.source_publication_id = sd.id
                  AND sa2.source = 'theses'
                  AND sa2.roles && ARRAY['author']::text[]
                LIMIT 1
               ) AS author_person_id,
               (SELECT ARRAY_AGG(DISTINCT sid)
                FROM authorships a,
                     UNNEST(a.structure_ids) AS sid
                JOIN structures st ON st.id = sid
                WHERE a.publication_id = p.id AND a.in_perimeter
                  AND st.structure_type = 'labo'
               ) AS structure_ids
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE sa.person_id = %s
          AND sa.source = 'theses'
          AND NOT (sa.roles && ARRAY['author']::text[])
        ORDER BY p.pub_year DESC NULLS LAST, p.title
        """,
        (person_id,),
    )
    rows = cur.fetchall()

    all_struct_ids: set[int] = set()
    for row in rows:
        for sid in row["structure_ids"] or []:
            all_struct_ids.add(sid)

    structures: dict[int, Any] = {}
    if all_struct_ids:
        cur.execute(
            "SELECT id, acronym, name FROM structures WHERE id = ANY(%s)",
            (list(all_struct_ids),),
        )
        for s in cur.fetchall():
            structures[s["id"]] = {"acronym": s["acronym"], "name": s["name"]}

    by_role: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        roles = row["roles"] or []
        role = "jury_member"
        for r in _THESIS_ROLES:
            if r in roles:
                role = r
                break
        by_role.setdefault(role, []).append(
            {
                "id": row["id"],
                "title": row["title"],
                "pub_year": row["pub_year"],
                "doi": row["doi"],
                "author_name": row["author_name"],
                "author_person_id": row["author_person_id"],
                "structure_ids": row["structure_ids"] or [],
            }
        )

    sections = [
        {"role": k, "label": _THESIS_ROLE_LABELS[k], "theses": by_role[k]}
        for k in _THESIS_ROLES
        if k in by_role
    ]
    return {"sections": sections, "total": len(rows), "structures": structures}


# ── Adresses ─────────────────────────────────────────────────────


def person_addresses(cur: Any, person_id: int, *, page: int, per_page: int) -> dict[str, Any]:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    base_where = """a.id IN (
            SELECT DISTINCT saa.address_id
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            WHERE sa.person_id = %s
        )"""
    cur.execute(f"SELECT COUNT(*) AS total FROM addresses a WHERE {base_where}", (person_id,))
    total = cur.fetchone()["total"]
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    cur.execute(
        f"""
        SELECT a.id, a.raw_text,
               (SELECT jsonb_agg(jsonb_build_object(
                    'id', s.id, 'acronym', s.acronym, 'name', s.name))
                FROM address_structures ast
                JOIN structures s ON s.id = ast.structure_id
                WHERE ast.address_id = a.id AND s.structure_type != 'site'
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
               ) AS structures
        FROM addresses a
        WHERE {base_where}
        ORDER BY a.raw_text
        LIMIT %s OFFSET %s
        """,
        (person_id, per_page, offset),
    )
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "addresses": cur.fetchall(),
    }
