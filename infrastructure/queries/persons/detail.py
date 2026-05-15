"""Détail d'une personne (sync) : profil, auteurs liés, thèses encadrées, adresses."""

import datetime
from typing import Any

from sqlalchemy import Connection, text

from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from infrastructure.queries.filters import OA_CLOSED_SQL

# Filtre étendu pour les stats de contribution effective : OUT_OF_SCOPE
# (peer_review, memoir) + ongoing_thesis (les thèses en cours ne comptent
# pas comme contribution finalisée à un sujet).
_DOC_TYPES_EXCLUDED_FROM_CONTRIBUTIONS = sorted(OUT_OF_SCOPE_DOC_TYPES | {"ongoing_thesis"})
_DOC_TYPES_EXCLUDED_FROM_CONTRIBUTIONS_SQL = (
    "(" + ", ".join(f"'{t}'" for t in _DOC_TYPES_EXCLUDED_FROM_CONTRIBUTIONS) + ")"
)


def get_person(conn: Connection, person_id: int) -> dict[str, Any] | None:
    """Détail d'une personne avec auteurs liés (admin)."""
    row = conn.execute(
        text("""
            SELECT p.id, p.last_name, p.first_name,
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh,
                (SELECT json_agg(x) FROM (
                    SELECT MIN(sa.id) AS id, sa.source,
                           sa.raw_author_name AS full_name
                    FROM source_authorships sa
                    WHERE sa.person_id = p.id AND NOT sa.excluded
                    GROUP BY sa.source, sa.raw_author_name
                    ORDER BY sa.source, sa.raw_author_name
                ) x) AS linked_authors,
                (SELECT json_agg(json_build_object(
                    'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                    'source', pi.source, 'status', pi.status
                ) ORDER BY pi.id_type, pi.id_value)
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id
                   AND pi.id_type = ANY(:public_id_types)
                ) AS identifiers
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = :pid
        """),
        {"pid": person_id, "public_id_types": list(PUBLIC_PERSON_IDENTIFIER_TYPES)},
    ).one_or_none()
    return dict(row._mapping) if row else None


def person_profile(conn: Connection, person_id: int) -> dict[str, Any] | None:
    """Profil public : infos + identifiants + auteurs liés."""
    person_row = conn.execute(
        text("""
            SELECT p.id, p.last_name, p.first_name,
                   prh.role_title, prh.department_name,
                   prh.start_date, prh.end_date
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = :pid
        """),
        {"pid": person_id},
    ).one_or_none()
    if not person_row:
        return None
    person = dict(person_row._mapping)

    id_rows = conn.execute(
        text("""
            SELECT id, id_type, id_value, source, status
            FROM person_identifiers
            WHERE person_id = :pid
              AND id_type = ANY(:public_id_types)
        """),
        {"pid": person_id, "public_id_types": list(PUBLIC_PERSON_IDENTIFIER_TYPES)},
    ).all()
    identifiers = [dict(r._mapping) for r in id_rows]

    # Reconstitution de la vue « comptes HAL » depuis source_authorships
    # agrégés par hal_person_id (1 row par compte HAL pour cette personne).
    # MIN() arbitraire mais déterministe sur les champs descriptifs : en
    # théorie constants pour un même hal_person_id (attachés au compte
    # HAL, pas à la signature).
    hal_rows = conn.execute(
        text("""
            SELECT MIN(sa.id) AS id,
                   'hal' AS source,
                   MIN(sa.raw_author_name) AS full_name,
                   MIN(sa.person_identifiers->>'orcid') AS orcid,
                   MIN(sa.person_identifiers->>'idhal') AS idhal,
                   (sa.person_identifiers->>'hal_person_id')::int AS hal_person_id,
                   NULL::text AS openalex_id,
                   COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS uca_pub_count
            FROM source_authorships sa
            WHERE sa.source = 'hal'
              AND sa.person_id = :pid
              AND NOT sa.excluded
              AND sa.person_identifiers->>'hal_person_id' IS NOT NULL
            GROUP BY sa.person_identifiers->>'hal_person_id'
        """),
        {"pid": person_id},
    ).all()
    hal_authors = [dict(r._mapping) for r in hal_rows]

    oa_rows = conn.execute(
        text("""
            SELECT MIN(sa.id) AS id,
                   sa.raw_author_name AS full_name,
                   'openalex' AS source,
                   NULL::text AS orcid, NULL::text AS idhal, NULL::text AS openalex_id,
                   COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS uca_pub_count
            FROM source_authorships sa
            WHERE sa.source = 'openalex' AND sa.person_id = :pid
            GROUP BY sa.raw_author_name
        """),
        {"pid": person_id},
    ).all()
    oa_authors = [dict(r._mapping) for r in oa_rows]

    # WoS : group by raw_author_name comme OpenAlex. ORCID lu depuis
    # source_authorships.person_identifiers.
    wos_rows = conn.execute(
        text("""
            SELECT MIN(sa.id) AS id,
                   sa.raw_author_name AS full_name,
                   'wos' AS source,
                   MAX(sa.person_identifiers->>'orcid') AS orcid,
                   NULL::text AS idhal, NULL::text AS openalex_id,
                   COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS uca_pub_count
            FROM source_authorships sa
            WHERE sa.source = 'wos' AND sa.person_id = :pid
            GROUP BY sa.raw_author_name
        """),
        {"pid": person_id},
    ).all()
    wos_authors = [dict(r._mapping) for r in wos_rows]

    theses_count_row = conn.execute(
        text("""
            SELECT COUNT(*) AS count
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.person_id = :pid
              AND sa.source = 'theses'
              AND NOT (sa.roles && ARRAY['author']::text[])
              AND sd.publication_id IS NOT NULL
        """),
        {"pid": person_id},
    ).one()

    return {
        "person": person,
        "identifiers": identifiers,
        "authors": hal_authors + oa_authors + wos_authors,
        "theses_count": theses_count_row.count,
    }


# ── Thèses encadrées ─────────────────────────────────────────────


_THESIS_ROLES = ("thesis_director", "rapporteur", "jury_president", "jury_member")
_THESIS_ROLE_LABELS = {
    "thesis_director": "Directeur/directrice de thèse",
    "rapporteur": "Rapporteur",
    "jury_president": "Président du jury",
    "jury_member": "Membre du jury",
}


def person_theses(conn: Connection, person_id: int) -> dict[str, Any]:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    rows = conn.execute(
        text("""
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
            WHERE sa.person_id = :pid
              AND sa.source = 'theses'
              AND NOT (sa.roles && ARRAY['author']::text[])
            ORDER BY p.pub_year DESC NULLS LAST, p.title
        """),
        {"pid": person_id},
    ).all()

    all_struct_ids: set[int] = set()
    for row in rows:
        for sid in row.structure_ids or []:
            all_struct_ids.add(sid)

    structures: dict[int, Any] = {}
    if all_struct_ids:
        struct_rows = conn.execute(
            text("SELECT id, acronym, name FROM structures WHERE id = ANY(:ids)"),
            {"ids": list(all_struct_ids)},
        ).all()
        for s in struct_rows:
            structures[s.id] = {"acronym": s.acronym, "name": s.name}

    by_role: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        roles = row.roles or []
        role = "jury_member"
        for r in _THESIS_ROLES:
            if r in roles:
                role = r
                break
        by_role.setdefault(role, []).append(
            {
                "id": row.id,
                "title": row.title,
                "pub_year": row.pub_year,
                "doi": row.doi,
                "author_name": row.author_name,
                "author_person_id": row.author_person_id,
                "structure_ids": row.structure_ids or [],
            }
        )

    sections = [
        {"role": k, "label": _THESIS_ROLE_LABELS[k], "theses": by_role[k]}
        for k in _THESIS_ROLES
        if k in by_role
    ]
    return {"sections": sections, "total": len(rows), "structures": structures}


# ── Adresses ─────────────────────────────────────────────────────


def person_addresses(
    conn: Connection, person_id: int, *, page: int, per_page: int
) -> dict[str, Any]:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    base_where = """a.id IN (
            SELECT DISTINCT saa.address_id
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            WHERE sa.person_id = :pid
        )"""
    count_row = conn.execute(
        text(f"SELECT COUNT(*) AS total FROM addresses a WHERE {base_where}"),
        {"pid": person_id},
    ).one()
    total = count_row.total
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    rows = conn.execute(
        text(f"""
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
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {"pid": person_id, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "addresses": [dict(r._mapping) for r in rows],
    }


def person_subjects(conn: Connection, person_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    """Top sujets des publications d'une personne, ordonnés par fréquence.

    Exclut les sujets trop génériques (`subjects.usage_count` > 5000).
    """
    rows = conn.execute(
        text(f"""
            SELECT s.id, s.label, s.ontologies, COUNT(DISTINCT p.id) AS count
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            JOIN publication_subjects ps ON ps.publication_id = p.id
            JOIN subjects s ON s.id = ps.subject_id
            WHERE a.person_id = :pid
              AND a.roles && ARRAY['author']::text[]
              AND p.doc_type NOT IN {_DOC_TYPES_EXCLUDED_FROM_CONTRIBUTIONS_SQL}
              AND s.usage_count <= 5000
            GROUP BY s.id, s.label, s.ontologies
            ORDER BY count DESC, lower(s.label)
            LIMIT :lim
        """),
        {"pid": person_id, "lim": limit},
    ).all()
    return [dict(r._mapping) for r in rows]


def person_dashboard(conn: Connection, person_id: int) -> dict[str, Any]:
    """Dashboard personne : publis/an + répartition Open Access."""
    current_year = datetime.date.today().year

    pubs_year_rows = conn.execute(
        text("""
            SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id
            WHERE a.person_id = :pid
              AND a.roles && ARRAY['author']::text[]
              AND p.pub_year IS NOT NULL
              AND p.pub_year >= :min_year
            GROUP BY p.pub_year
            ORDER BY p.pub_year
        """),
        {"pid": person_id, "min_year": current_year - 6},
    ).all()
    pubs_by_year = [{"year": r.pub_year, "count": r.count} for r in pubs_year_rows]

    oa = conn.execute(
        text(f"""
            SELECT
                COUNT(DISTINCT p.id) FILTER (
                    WHERE p.oa_status NOT IN {OA_CLOSED_SQL} AND p.oa_status IS NOT NULL
                ) AS open_access,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                COUNT(DISTINCT p.id) FILTER (
                    WHERE p.oa_status = 'unknown' OR p.oa_status IS NULL
                ) AS unknown,
                COUNT(DISTINCT p.id) AS total
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id
            WHERE a.person_id = :pid
              AND a.roles && ARRAY['author']::text[]
        """),
        {"pid": person_id},
    ).one()

    return {
        "pubs_by_year": pubs_by_year,
        "oa": {
            "open_access": oa.open_access,
            "closed": oa.closed,
            "unknown": oa.unknown,
            "total": oa.total,
        },
    }
