"""Persons router: directory, search, list, profile, merge, identifiers, authors."""

import os
import re
import sys
from fastapi import APIRouter, Query, HTTPException, Depends
from webapp.deps import get_cursor, require_admin
from webapp.models import LinkPersonAuthor, AddIdentifier
from webapp.filters import (PUB_IS_UCA, OA_OPEN_STATUSES, persons_sort_clause,
    parse_int_csv, parse_str_csv, apply_source_filter)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils.normalize import normalize_text
from utils.merge_persons import merge_person as _merge_person

router = APIRouter()

@router.get("/api/persons/directory")
async def persons_directory(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),      # comma-separated
    role: str = Query(""),            # comma-separated
    has_orcid: str = Query(""),       # "yes" or "no"
    has_idhal: str = Query(""),       # "yes" or "no"
    has_rh: str = Query(""),          # "yes" or "no"
):
    """Annuaire public des personnes UCA avec ORCID et idHAL."""
    offset = (page - 1) * per_page

    departments = [v.strip() for v in department.split(',') if v.strip()] if department else []
    roles = [v.strip() for v in role.split(',') if v.strip()] if role else []

    conditions = []
    params = []

    if search:
        conditions.append("(unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s))")
        s = f"%{search}%"
        params.extend([s, s])
    if departments:
        conditions.append("prh.department_name = ANY(%s)")
        params.append(departments)
    if roles:
        conditions.append("prh.role_title = ANY(%s)")
        params.append(roles)
    if has_orcid == "yes":
        conditions.append(
            "EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')")
    elif has_orcid == "no":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')")
    if has_idhal == "yes":
        conditions.append("""(
            EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
            OR EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
        )""")
    elif has_idhal == "no":
        conditions.append("""(
            NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
            AND NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
        )""")
    if has_rh == "yes":
        conditions.append("prh.id IS NOT NULL")
    elif has_rh == "no":
        conditions.append("prh.id IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as (cur, conn):
        cur.execute(f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT
                p.id, p.last_name, p.first_name,
                prh.role_title, prh.department_name,
                (prh.id IS NOT NULL) AS has_rh,
                (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                ) AS orcids,
                (SELECT json_agg(json_build_object('value', sub.v, 'confirmed', sub.confirmed)) FROM (
                    SELECT DISTINCT ON (v) v, confirmed FROM (
                        SELECT ha.idhal AS v, false AS confirmed FROM hal_authors ha
                        WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM person_identifiers pi2
                              WHERE pi2.person_id = p.id AND pi2.id_type = 'idhal'
                                AND pi2.id_value = ha.idhal AND pi2.status = 'rejected')
                        UNION ALL
                        SELECT pi.id_value, (pi.status = 'confirmed') FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                    ) raw ORDER BY v, confirmed DESC
                ) sub) AS idhals
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            {where}
            ORDER BY LOWER(p.last_name), LOWER(p.first_name)
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "persons": cur.fetchall(),
        }


# ----- API: Stats -----


@router.get("/api/persons/search")
async def search_persons(q: str = Query("", min_length=2), limit: int = Query(10, ge=1, le=30)):
    """Recherche rapide de personnes (autocomplete)."""
    words = q.strip().split()
    if not words:
        return []
    # Each word must match in last_name OR first_name
    conditions = []
    params: list = []
    for w in words:
        s = f"%{w}%"
        conditions.append("(unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s))")
        params.extend([s, s])
    params.append(limit)
    with get_cursor() as (cur, conn):
        cur.execute(f"""
            SELECT p.id, p.last_name, p.first_name, prh.department_name,
                   (prh.id IS NOT NULL) AS has_rh
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {" AND ".join(conditions)}
            ORDER BY LOWER(p.last_name), LOWER(p.first_name)
            LIMIT %s
        """, params)
        return cur.fetchall()


@router.get("/api/persons")
async def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    linked: str = Query(""),  # "yes", "no", ""
    has_orcid: str = Query(""),  # "yes", "no", ""
    has_idhal: str = Query(""),  # "yes", "no", ""
    has_rh: str = Query(""),    # "yes", "no", ""
    sort: str = Query("name"),  # name, -name, pubs, -pubs
):
    """Liste des personnes avec filtres."""
    offset = (page - 1) * per_page
    conditions = []
    params = []

    if search:
        conditions.append("""(
            unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s)
            OR prh.email ILIKE %s OR unaccent(prh.department_name) ILIKE unaccent(%s)
        )""")
        s = f"%{search}%"
        params.extend([s, s, s, s])
    if department:
        conditions.append("prh.department_name = %s")
        params.append(department)
    if role:
        conditions.append("prh.role_title = %s")
        params.append(role)
    if linked == "yes":
        conditions.append("""(EXISTS (
            SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id
        ) OR EXISTS (
            SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id
        ))""")
    elif linked == "no":
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id
        ) AND NOT EXISTS (
            SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id
        )""")
    if has_orcid == "yes":
        conditions.append("""EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
        )""")
    elif has_orcid == "no":
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
        )""")
    if has_idhal == "yes":
        conditions.append("""EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
        )""")
    elif has_idhal == "no":
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
        )""")
    if has_rh == "yes":
        conditions.append("prh.id IS NOT NULL")
    elif has_rh == "no":
        conditions.append("prh.id IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as (cur, conn):
        cur.execute(f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT p.id, p.last_name, p.first_name,
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id AND a.is_uca = TRUE) AS uca_pub_count,
                (SELECT json_agg(x) FROM (
                    SELECT ha.id, ha.full_name, ha.orcid, ha.idhal, 'hal' AS source
                    FROM hal_authors ha WHERE ha.person_id = p.id
                    UNION ALL
                    SELECT oa.id, oa.full_name, oa.orcid, NULL AS idhal, 'openalex' AS source
                    FROM openalex_authors oa WHERE oa.person_id = p.id
                    UNION ALL
                    SELECT wa.id, wa.full_name, wa.orcid, NULL AS idhal, 'wos' AS source
                    FROM wos_authors wa WHERE wa.person_id = p.id
                ) x) AS linked_authors,
                (SELECT json_agg(json_build_object(
                    'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                    'source', pi.source, 'status', pi.status
                ) ORDER BY pi.id_type, pi.id_value) FROM person_identifiers pi WHERE pi.person_id = p.id
                ) AS identifiers
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            {where}
            ORDER BY {
                {
                    "name": "p.last_name ASC, p.first_name ASC",
                    "-name": "p.last_name DESC, p.first_name DESC",
                    "pubs": "pub_count ASC, p.last_name ASC",
                    "-pubs": "pub_count DESC, p.last_name ASC",
                }.get(sort, "p.last_name ASC, p.first_name ASC")
            }
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "persons": cur.fetchall(),
        }


@router.get("/api/persons/facets")
async def persons_facets(
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_rh: str = Query(""),
    linked: str = Query(""),
):
    """Facettes dynamiques pour la page personnes.
    Chaque facette exclut son propre filtre."""
    departments = parse_str_csv(department)
    roles = parse_str_csv(role)

    def base_filters(*, skip: str) -> tuple[list[str], list]:
        conds: list[str] = []
        params: list = []
        if skip != "department" and departments:
            conds.append("prh.department_name = ANY(%s)")
            params.append(departments)
        if skip != "role" and roles:
            conds.append("prh.role_title = ANY(%s)")
            params.append(roles)
        if skip != "has_orcid":
            if has_orcid == "yes":
                conds.append("EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')")
            elif has_orcid == "no":
                conds.append("NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')")
        if skip != "has_idhal":
            if has_idhal == "yes":
                conds.append("""(
                    EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    OR EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
                )""")
            elif has_idhal == "no":
                conds.append("""(
                    NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    AND NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
                )""")
        if skip != "has_rh":
            if has_rh == "yes":
                conds.append("prh.id IS NOT NULL")
            elif has_rh == "no":
                conds.append("prh.id IS NULL")
        if skip != "linked":
            if linked == "yes":
                conds.append("""(EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                    OR EXISTS (SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id))""")
            elif linked == "no":
                conds.append("""NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                    AND NOT EXISTS (SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id)""")
        return conds, params

    base_from = "persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id"

    with get_cursor() as (cur, conn):
        # --- Facette DÉPARTEMENTS ---
        c, p = base_filters(skip="department")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(f"""
            SELECT prh.department_name AS value, COUNT(*) AS count
            FROM {base_from}
            {where} {"AND" if c else "WHERE"} prh.department_name IS NOT NULL
            GROUP BY prh.department_name ORDER BY count DESC
        """, p)
        dept_facets = cur.fetchall()

        # --- Facette RÔLES ---
        c, p = base_filters(skip="role")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(f"""
            SELECT prh.role_title AS value, COUNT(*) AS count
            FROM {base_from}
            {where} {"AND" if c else "WHERE"} prh.role_title IS NOT NULL
            GROUP BY prh.role_title ORDER BY count DESC
        """, p)
        role_facets = cur.fetchall()

        # --- Facettes booléennes (orcid, idhal, rh) : comptages yes/no ---
        c, p = base_filters(skip="has_orcid")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM person_identifiers pi
                    WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                )) AS yes,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM person_identifiers pi
                    WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                )) AS no
            FROM {base_from} {where}
        """, p)
        orcid_counts = cur.fetchone()

        c, p = base_filters(skip="has_idhal")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE
                    EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    OR EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
                ) AS yes,
                COUNT(*) FILTER (WHERE
                    NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    AND NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
                ) AS no
            FROM {base_from} {where}
        """, p)
        idhal_counts = cur.fetchone()

        c, p = base_filters(skip="has_rh")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE prh.id IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE prh.id IS NULL) AS no
            FROM {base_from} {where}
        """, p)
        rh_counts = cur.fetchone()

        # --- Facette LINKED (admin uniquement) ---
        linked_counts = None
        if linked or True:  # toujours calculer pour que l'admin puisse l'utiliser
            c, p = base_filters(skip="linked")
            where = ("WHERE " + " AND ".join(c)) if c else ""
            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE
                        EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                        OR EXISTS (SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id)
                    ) AS yes,
                    COUNT(*) FILTER (WHERE
                        NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                        AND NOT EXISTS (SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id)
                    ) AS no
                FROM {base_from} {where}
            """, p)
            linked_counts = cur.fetchone()

        return {
            "departments": dept_facets,
            "roles": role_facets,
            "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
            "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
            "rh": {"yes": rh_counts["yes"], "no": rh_counts["no"]},
            "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]} if linked_counts else None,
        }


@router.get("/api/persons/departments")
async def list_departments():
    """Liste des départements distincts."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT department_name, COUNT(*) AS count
            FROM persons_rh
            WHERE department_name IS NOT NULL
            GROUP BY department_name
            ORDER BY count DESC
        """)
        return cur.fetchall()


@router.get("/api/persons/roles")
async def list_roles():
    """Liste des rôles distincts."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT role_title, COUNT(*) AS count
            FROM persons_rh
            WHERE role_title IS NOT NULL
            GROUP BY role_title
            ORDER BY count DESC
        """)
        return cur.fetchall()


@router.get("/api/persons/stats")
async def persons_stats():
    """Statistiques sur les personnes et l'alignement."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT
                COUNT(*) AS total_persons,
                COUNT(DISTINCT p.id) FILTER (
                    WHERE EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                       OR EXISTS (SELECT 1 FROM openalex_authorships oas WHERE oas.person_id = p.id)
                       OR EXISTS (SELECT 1 FROM wos_authors wa WHERE wa.person_id = p.id)
                ) AS linked_persons,
                (SELECT COUNT(*) FROM hal_authors WHERE person_id IS NOT NULL)
                + (SELECT COUNT(DISTINCT person_id) FROM openalex_authorships WHERE person_id IS NOT NULL)
                + (SELECT COUNT(*) FROM wos_authors WHERE person_id IS NOT NULL)
                AS linked_authors,
                (SELECT COUNT(DISTINCT department_name)
                 FROM persons_rh WHERE department_name IS NOT NULL) AS departments
            FROM persons p
        """)
        return cur.fetchone()


@router.get("/api/authors/{source}/{author_id}/details")
async def author_details(source: str, author_id: int, max_pubs: int = Query(10, ge=1, le=50)):
    """Détails d'un auteur source : ses publications récentes."""
    with get_cursor() as (cur, conn):
        if source == "hal":
            cur.execute("""
                SELECT p.id, p.title, p.pub_year, p.doi,
                       has.is_uca,
                       'hal' AS source
                FROM hal_authorships has
                JOIN hal_documents hd ON hd.id = has.hal_document_id
                LEFT JOIN publications p ON p.id = hd.publication_id
                WHERE has.hal_author_id = %s AND has.is_uca = TRUE
                ORDER BY COALESCE(p.pub_year, hd.pub_year) DESC
                LIMIT %s
            """, (author_id, max_pubs))
        elif source == "openalex":
            cur.execute("""
                SELECT p.id, p.title, p.pub_year, p.doi,
                       oas.is_uca,
                       'openalex' AS source
                FROM openalex_authorships oas
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                LEFT JOIN publications p ON p.id = od.publication_id
                WHERE oas.openalex_author_id = %s AND oas.is_uca = TRUE
                ORDER BY COALESCE(p.pub_year, od.pub_year) DESC
                LIMIT %s
            """, (author_id, max_pubs))
        elif source == "wos":
            cur.execute("""
                SELECT p.id, p.title, p.pub_year, p.doi,
                       was.is_uca,
                       'wos' AS source
                FROM wos_authorships was
                JOIN wos_documents wd ON wd.id = was.wos_document_id
                LEFT JOIN publications p ON p.id = wd.publication_id
                WHERE was.wos_author_id = %s AND was.is_uca = TRUE
                ORDER BY COALESCE(p.pub_year, wd.pub_year) DESC
                LIMIT %s
            """, (author_id, max_pubs))
        else:
            raise HTTPException(status_code=400, detail="Source must be 'hal', 'openalex' or 'wos'")

        publications = cur.fetchall()
        return {"signatures": [], "publications": publications}


@router.get("/api/persons/{person_id}")
async def get_person(person_id: int):
    """Retourne une personne avec ses auteurs liés."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT p.id, p.last_name, p.first_name,
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh,
                (SELECT json_agg(x) FROM (
                    SELECT ha.id, ha.full_name, ha.orcid, ha.idhal, 'hal' AS source
                    FROM hal_authors ha WHERE ha.person_id = p.id
                    UNION ALL
                    SELECT oa.id, oa.full_name, oa.orcid, NULL AS idhal, 'openalex' AS source
                    FROM openalex_authors oa WHERE oa.person_id = p.id
                    UNION ALL
                    SELECT wa.id, wa.full_name, wa.orcid, NULL AS idhal, 'wos' AS source
                    FROM wos_authors wa WHERE wa.person_id = p.id
                ) x) AS linked_authors,
                (SELECT json_agg(json_build_object(
                    'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                    'source', pi.source, 'status', pi.status
                ) ORDER BY pi.id_type, pi.id_value) FROM person_identifiers pi WHERE pi.person_id = p.id
                ) AS identifiers
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = %s
        """, (person_id,))
        person = cur.fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        return person


@router.get("/api/persons/{person_id}/profile")
async def person_profile(person_id: int):
    """Profil public complet d'une personne : infos, identifiants, auteurs liés."""
    with get_cursor() as (cur, conn):
        # Infos personne
        cur.execute("""
            SELECT p.id, p.last_name, p.first_name,
                   prh.role_title, prh.department_name,
                   prh.start_date, prh.end_date
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = %s
        """, (person_id,))
        person = cur.fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")

        # Identifiants
        cur.execute("""
            SELECT id, id_type, id_value, source, status
            FROM person_identifiers WHERE person_id = %s
        """, (person_id,))
        identifiers = cur.fetchall()

        # Auteurs liés HAL + compte publis UCA
        cur.execute("""
            SELECT ha.id, 'hal' AS source, ha.full_name, ha.orcid, ha.idhal,
                   ha.hal_person_id,
                   NULL::text AS openalex_id,
                   (SELECT COUNT(*) FROM hal_authorships has2
                    WHERE has2.hal_author_id = ha.id AND has2.is_uca = TRUE) AS uca_pub_count
            FROM hal_authors ha WHERE ha.person_id = %s
        """, (person_id,))
        hal_authors = cur.fetchall()

        # Auteurs liés OpenAlex + compte publis UCA
        cur.execute("""
            SELECT oa.id, 'openalex' AS source, oa.full_name, oa.orcid,
                   NULL::text AS idhal, oa.openalex_id,
                   (SELECT COUNT(*) FROM openalex_authorships oas2
                    WHERE oas2.openalex_author_id = oa.id AND oas2.is_uca = TRUE) AS uca_pub_count
            FROM openalex_authors oa
            WHERE oa.id IN (SELECT DISTINCT oas.openalex_author_id FROM openalex_authorships oas WHERE oas.person_id = %s)
        """, (person_id,))
        oa_authors = cur.fetchall()

        # Auteurs liés WoS + compte publis UCA
        cur.execute("""
            SELECT wa.id, 'wos' AS source, wa.full_name, wa.orcid,
                   NULL::text AS idhal, NULL::text AS openalex_id,
                   (SELECT COUNT(*) FROM wos_authorships was2
                    WHERE was2.wos_author_id = wa.id AND was2.is_uca = TRUE) AS uca_pub_count
            FROM wos_authors wa WHERE wa.person_id = %s
        """, (person_id,))
        wos_authors = cur.fetchall()

        return {
            "person": person,
            "identifiers": identifiers,
            "authors": hal_authors + oa_authors + wos_authors,
        }


@router.get("/api/persons/{person_id}/addresses")
async def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """Adresses distinctes utilisées dans les authorships OpenAlex de cette personne."""
    with get_cursor() as (cur, conn):
        base_where = """a.id IN (
                SELECT DISTINCT oaa.address_id
                FROM openalex_authorship_addresses oaa
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                WHERE oas.person_id = %s
            )"""
        cur.execute(f"SELECT COUNT(*) AS total FROM addresses a WHERE {base_where}", (person_id,))
        total = cur.fetchone()["total"]
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        offset = (page - 1) * per_page

        cur.execute(f"""
            SELECT a.id, a.raw_text,
                   (SELECT jsonb_agg(jsonb_build_object(
                        'id', s.id, 'acronym', s.acronym, 'name', s.name))
                    FROM address_structures ast
                    JOIN structures s ON s.id = ast.structure_id
                    WHERE ast.address_id = a.id AND s.structure_type != 'site'
                   ) AS structures
            FROM addresses a
            WHERE {base_where}
            ORDER BY a.raw_text
            LIMIT %s OFFSET %s
        """, (person_id, per_page, offset))
        return {
            "total": total,
            "page": page,
            "pages": pages,
            "addresses": cur.fetchall(),
        }


@router.get("/api/persons/{person_id}/candidates")
async def person_author_candidates(person_id: int, limit: int = Query(10, ge=1, le=50)):
    """Cherche des auteurs candidats pour une personne (matching par nom ou ORCID)."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT * FROM persons WHERE id = %s", (person_id,))
        person = cur.fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")

        last_norm = person["last_name_normalized"]
        first_norm = person["first_name_normalized"]
        first_initial = first_norm[:1] if first_norm else ""
        # Build full name words for robust matching (handles compound names
        # like "Le Bras" where source may split name differently)
        full_words = sorted(set((last_norm + " " + first_norm).split()))

        # Person's ORCID (if any)
        cur.execute("""
            SELECT id_value FROM person_identifiers
            WHERE person_id = %s AND id_type = 'orcid' LIMIT 1
        """, (person_id,))
        orcid_row = cur.fetchone()
        person_orcid = orcid_row["id_value"] if orcid_row else None

        # Build SQL condition: each word from the person's full name must
        # appear in the author's full_name (accent-insensitive)
        word_conditions_hal = " AND ".join(
            "lower(unaccent(ha.full_name)) LIKE %s" for _ in full_words
        )
        word_conditions_oa = " AND ".join(
            "lower(unaccent(oa.full_name)) LIKE %s" for _ in full_words
        )
        word_params = [f"%{w}%" for w in full_words]

        # Add ORCID matching condition
        if person_orcid:
            orcid_cond_hal = "OR ha.orcid = %s"
            orcid_cond_oa = "OR oa.orcid = %s"
            orcid_cond_wos = "OR wa.orcid = %s"
            orcid_params = [person_orcid]
        else:
            orcid_cond_hal = ""
            orcid_cond_oa = ""
            orcid_cond_wos = ""
            orcid_params = []

        word_conditions_wos = " AND ".join(
            "lower(unaccent(wa.full_name)) LIKE %s" for _ in full_words
        )

        cur.execute(f"""
            WITH candidates AS (
                SELECT ha.id, 'hal' AS source, ha.full_name, ha.last_name, ha.first_name,
                       ha.orcid, ha.idhal, NULL::text AS openalex_id, ha.person_id,
                       (SELECT COUNT(*) FROM hal_authorships has2
                        WHERE has2.hal_author_id = ha.id AND has2.is_uca = TRUE) AS uca_pub_count,
                       (SELECT COUNT(*) FROM hal_authorships has2
                        WHERE has2.hal_author_id = ha.id) AS pub_count
                FROM hal_authors ha
                WHERE ({word_conditions_hal} {orcid_cond_hal})
                  AND EXISTS (SELECT 1 FROM hal_authorships has
                              WHERE has.hal_author_id = ha.id AND has.is_uca = TRUE)
                UNION ALL
                SELECT oa.id, 'openalex' AS source, oa.full_name, oa.last_name, oa.first_name,
                       oa.orcid, NULL::text AS idhal, oa.openalex_id, oa.person_id,
                       (SELECT COUNT(*) FROM openalex_authorships oas2
                        WHERE oas2.openalex_author_id = oa.id AND oas2.is_uca = TRUE) AS uca_pub_count,
                       (SELECT COUNT(*) FROM openalex_authorships oas2
                        WHERE oas2.openalex_author_id = oa.id) AS pub_count
                FROM openalex_authors oa
                WHERE ({word_conditions_oa} {orcid_cond_oa})
                  AND EXISTS (SELECT 1 FROM openalex_authorships oas
                              WHERE oas.openalex_author_id = oa.id AND oas.is_uca = TRUE)
                UNION ALL
                SELECT wa.id, 'wos' AS source, wa.full_name, wa.last_name, wa.first_name,
                       wa.orcid, NULL::text AS idhal, NULL::text AS openalex_id, wa.person_id,
                       (SELECT COUNT(*) FROM wos_authorships was2
                        WHERE was2.wos_author_id = wa.id AND was2.is_uca = TRUE) AS uca_pub_count,
                       (SELECT COUNT(*) FROM wos_authorships was2
                        WHERE was2.wos_author_id = wa.id) AS pub_count
                FROM wos_authors wa
                WHERE ({word_conditions_wos} {orcid_cond_wos})
                  AND EXISTS (SELECT 1 FROM wos_authorships was
                              WHERE was.wos_author_id = wa.id AND was.is_uca = TRUE)
            )
            SELECT * FROM candidates
            WHERE uca_pub_count > 0
            ORDER BY uca_pub_count DESC, pub_count DESC
            LIMIT %s
        """, word_params + orcid_params + word_params + orcid_params + word_params + orcid_params + [limit])

        return cur.fetchall()


@router.post("/api/persons/{person_id}/link")
async def link_person_to_author(person_id: int, data: LinkPersonAuthor):
    """Rattache un auteur source à une personne."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Person not found")

        if data.source == "hal":
            cur.execute("SELECT id, idhal, orcid FROM hal_authors WHERE id = %s",
                        (data.author_id,))
            ha = cur.fetchone()
            if not ha:
                raise HTTPException(status_code=404, detail="HAL author not found")
            cur.execute("""
                UPDATE hal_authors SET person_id = %s, updated_at = now()
                WHERE id = %s
            """, (person_id, data.author_id))
            # Propager vers authorships (vérité)
            cur.execute("""
                UPDATE authorships ash SET person_id = %s, updated_at = now()
                WHERE ash.hal_authorship_id IN (
                    SELECT has.id FROM hal_authorships has
                    WHERE has.hal_author_id = %s
                )
                AND ash.person_id IS NULL
            """, (person_id, data.author_id))
            # Propager identifiants vers person_identifiers
            if ha["idhal"]:
                cur.execute("""
                    INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                    VALUES (%s, 'idhal', %s, 'hal')
                    ON CONFLICT (id_type, id_value) DO NOTHING
                """, (person_id, ha["idhal"]))
            if ha["orcid"]:
                cur.execute("""
                    INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                    VALUES (%s, 'orcid', %s, 'hal')
                    ON CONFLICT (id_type, id_value) DO NOTHING
                """, (person_id, ha["orcid"]))
        elif data.source == "openalex":
            cur.execute("SELECT id, orcid FROM openalex_authors WHERE id = %s",
                        (data.author_id,))
            oa = cur.fetchone()
            if not oa:
                raise HTTPException(status_code=404, detail="OpenAlex author not found")
            cur.execute("""
                UPDATE openalex_authorships SET person_id = %s
                WHERE openalex_author_id = %s
            """, (person_id, data.author_id))
            cur.execute("""
                UPDATE authorships ash SET person_id = %s, updated_at = now()
                WHERE ash.openalex_authorship_id IN (
                    SELECT oas.id FROM openalex_authorships oas
                    WHERE oas.openalex_author_id = %s
                )
                AND ash.person_id IS NULL
            """, (person_id, data.author_id))
            # Propager ORCID vers person_identifiers
            if oa["orcid"]:
                cur.execute("""
                    INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                    VALUES (%s, 'orcid', %s, 'openalex')
                    ON CONFLICT (id_type, id_value) DO NOTHING
                """, (person_id, oa["orcid"]))
        elif data.source == "wos":
            cur.execute("SELECT id, orcid FROM wos_authors WHERE id = %s",
                        (data.author_id,))
            wa = cur.fetchone()
            if not wa:
                raise HTTPException(status_code=404, detail="WoS author not found")
            cur.execute("""
                UPDATE wos_authors SET person_id = %s, updated_at = now()
                WHERE id = %s
            """, (person_id, data.author_id))
            cur.execute("""
                UPDATE authorships ash SET person_id = %s, updated_at = now()
                WHERE ash.wos_authorship_id IN (
                    SELECT was.id FROM wos_authorships was
                    WHERE was.wos_author_id = %s
                )
                AND ash.person_id IS NULL
            """, (person_id, data.author_id))
            # Propager ORCID vers person_identifiers
            if wa["orcid"]:
                cur.execute("""
                    INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                    VALUES (%s, 'orcid', %s, 'wos')
                    ON CONFLICT (id_type, id_value) DO NOTHING
                """, (person_id, wa["orcid"]))
        else:
            raise HTTPException(status_code=400, detail="Source must be 'hal', 'openalex' or 'wos'")

        return {"linked": True, "person_id": person_id,
                "author_id": data.author_id, "source": data.source}


@router.delete("/api/persons/{person_id}/link/{source}/{author_id}")
async def unlink_person_from_author(person_id: int, source: str, author_id: int):
    """Détache un auteur source d'une personne."""
    with get_cursor() as (cur, conn):
        if source == "hal":
            cur.execute("""
                UPDATE hal_authors SET person_id = NULL, updated_at = now()
                WHERE id = %s AND person_id = %s
            """, (author_id, person_id))
        elif source == "openalex":
            cur.execute("""
                UPDATE openalex_authorships SET person_id = NULL
                WHERE openalex_author_id = %s
            """, (author_id,))
        elif source == "wos":
            cur.execute("""
                UPDATE wos_authors SET person_id = NULL, updated_at = now()
                WHERE id = %s AND person_id = %s
            """, (author_id, person_id))
        else:
            raise HTTPException(status_code=400, detail="Source must be 'hal', 'openalex' or 'wos'")

        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Link not found")
        return {"unlinked": True}


# ----- Identifier management -----

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@router.post("/api/persons/{person_id}/identifier")
async def add_person_identifier(person_id: int, data: AddIdentifier):
    """Ajoute manuellement un identifiant (ORCID ou idHAL) à une personne."""
    if data.id_type not in ("orcid", "idhal"):
        raise HTTPException(status_code=400, detail="id_type doit être 'orcid' ou 'idhal'")

    id_value = data.id_value.strip()

    # Nettoyage ORCID
    if data.id_type == "orcid":
        id_value = id_value.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
        if not ORCID_RE.match(id_value):
            raise HTTPException(
                status_code=400,
                detail=f"Format ORCID invalide : '{id_value}'. Attendu : 0000-0000-0000-000X"
            )

    if not id_value:
        raise HTTPException(status_code=400, detail="Valeur vide")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        # Vérifier si déjà attribué à une autre personne
        cur.execute(
            "SELECT person_id FROM person_identifiers WHERE id_type = %s AND id_value = %s",
            (data.id_type, id_value)
        )
        existing = cur.fetchone()
        if existing:
            if existing["person_id"] == person_id:
                return {"added": False, "reason": "already_exists"}
            raise HTTPException(
                status_code=409,
                detail=f"Cet identifiant est déjà attribué à la personne #{existing['person_id']}"
            )

        cur.execute("""
            INSERT INTO person_identifiers (person_id, id_type, id_value, source)
            VALUES (%s, %s, %s, 'manual')
        """, (person_id, data.id_type, id_value))

        return {"added": True, "id_type": data.id_type, "id_value": id_value}


@router.delete("/api/persons/{person_id}/identifier/{id_type}/{id_value:path}")
async def remove_person_identifier(person_id: int, id_type: str, id_value: str):
    """Supprime un identifiant d'une personne."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            DELETE FROM person_identifiers
            WHERE person_id = %s AND id_type = %s AND id_value = %s
        """, (person_id, id_type, id_value))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Identifiant introuvable")
        return {"removed": True}


@router.patch("/api/person-identifiers/{ident_id}/status")
async def update_identifier_status(ident_id: int, body: dict):
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    new_status = body.get("status")
    if new_status not in ("pending", "confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="Statut invalide")
    with get_cursor() as (cur, conn):
        cur.execute("""
            UPDATE person_identifiers SET status = %s::identifier_status
            WHERE id = %s RETURNING id, status
        """, (new_status, ident_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Identifiant introuvable")
        return {"id": row["id"], "status": row["status"]}


@router.patch("/api/authorships/{authorship_id}/exclude")
async def toggle_authorship_excluded(authorship_id: int):
    """Marque un authorship comme exclu (lien personne-publication rejeté)."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            UPDATE authorships SET excluded = TRUE, updated_at = now()
            WHERE id = %s RETURNING id, excluded
        """, (authorship_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Authorship introuvable")
        return {"id": row["id"], "excluded": row["excluded"]}


@router.post("/api/persons/{person_id}/merge")
async def merge_persons(person_id: int, body: dict):
    """Fusionne une autre personne (source) dans celle-ci (target)."""
    source_id = body.get("source_id")
    if not source_id or source_id == person_id:
        raise HTTPException(status_code=400, detail="source_id invalide")

    with get_cursor() as (cur, conn):
        # Vérifier que les deux personnes existent
        cur.execute("SELECT id FROM persons WHERE id IN (%s, %s)", (person_id, source_id))
        found = {row["id"] for row in cur.fetchall()}
        if person_id not in found:
            raise HTTPException(status_code=404, detail="Personne cible introuvable")
        if source_id not in found:
            raise HTTPException(status_code=404, detail="Personne source introuvable")

        try:
            _merge_person(cur, person_id, source_id)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))

        return {"merged": True, "source_id": source_id, "target_id": person_id}


# ----- API: Doublons personnes -----

def _person_name_tokens(ln_norm: str, fn_norm: str) -> set[str]:
    """Tokens du nom complet normalisé (last + first), tirets éclatés en espaces."""
    return set((ln_norm + " " + fn_norm).replace("-", " ").split()) - {""}


def _tokens_match(t1: set[str], t2: set[str]) -> bool:
    """Vérifie si les tokens matchent.

    Chaque token de l'ensemble le plus petit doit trouver un correspondant
    dans l'ensemble le plus grand : soit identique, soit initiale (1 lettre)
    correspondant au début d'un token de l'autre ensemble.
    """
    if not t1 or not t2:
        return False
    small, big = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    for s in small:
        if s in big:
            continue
        if len(s) == 1:
            # s est une initiale — cherche un token dans big commençant par s
            if any(b.startswith(s) for b in big):
                continue
        # Cherche si s correspond à l'expansion d'une initiale dans big
        if any(len(b) == 1 and s.startswith(b) for b in big):
            continue
        return False
    return True


_DUP_NOT_EXISTS = """
    WHERE NOT EXISTS (
        SELECT 1 FROM distinct_persons dp
        WHERE dp.person_id_a = LEAST(p1.id, p2.id) AND dp.person_id_b = GREATEST(p1.id, p2.id)
    )
    AND NOT (
        EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p1.id)
        AND EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p2.id)
    )
"""

# Requêtes de doublons personnes par priorité (exécutées séquentiellement)
PERSON_DUP_QUERIES = [
    # Priorité 1a : même nom, initiale vs prénom complet
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (LENGTH(p1.first_name_normalized) = 1 OR LENGTH(p2.first_name_normalized) = 1)
          AND LENGTH(p1.first_name_normalized) >= 1
          AND LENGTH(p2.first_name_normalized) >= 1
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",

    # Priorité 1b : nom composé vs nom simple
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND REPLACE(p1.last_name_normalized, '-', ' ') <> REPLACE(p2.last_name_normalized, '-', ' ')
          AND p1.last_name_normalized <> ''
          AND p2.last_name_normalized <> ''
          AND (
              REPLACE(p2.last_name_normalized, '-', ' ') LIKE REPLACE(p1.last_name_normalized, '-', ' ') || ' %%'
              OR REPLACE(p1.last_name_normalized, '-', ' ') LIKE REPLACE(p2.last_name_normalized, '-', ' ') || ' %%'
          )
          AND LENGTH(p1.first_name_normalized) >= 1
          AND LENGTH(p2.first_name_normalized) >= 1
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (
              p1.first_name_normalized = p2.first_name_normalized
              OR LENGTH(p1.first_name_normalized) = 1
              OR LENGTH(p2.first_name_normalized) = 1
              OR p1.first_name_normalized LIKE p2.first_name_normalized || ' %%'
              OR p2.first_name_normalized LIKE p1.first_name_normalized || ' %%'
          )
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",

    # Priorité 1c : inversion nom/prénom
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.first_name_normalized
          AND p1.first_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND p1.first_name_normalized <> ''
          AND p1.last_name_normalized <> p1.first_name_normalized
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",

    # Priorité 2 : même nom, prénoms compatibles (pas initiale)
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND LENGTH(p1.first_name_normalized) > 1
          AND LENGTH(p2.first_name_normalized) > 1
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (
              p1.first_name_normalized = p2.first_name_normalized
              OR p1.first_name_normalized LIKE p2.first_name_normalized || ' %%'
              OR p2.first_name_normalized LIKE p1.first_name_normalized || ' %%'
          )
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
]


def _get_person_dedup_detail(cur, person_id):
    """Détail d'une personne pour la page de déduplication."""
    cur.execute("""
        SELECT p.id, p.last_name, p.first_name,
               p.last_name_normalized, p.first_name_normalized,
               prh.role_title, prh.department_name,
               (prh.id IS NOT NULL) AS has_rh
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
    """, (person_id,))
    person = cur.fetchone()
    if not person:
        return None

    cur.execute("""
        SELECT id, id_type, id_value, source, status::text
        FROM person_identifiers WHERE person_id = %s
        ORDER BY id_type, id_value
    """, (person_id,))
    identifiers = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT pub.id, pub.title, pub.pub_year, pub.doi, pub.doc_type::text,
               ARRAY_REMOVE(ARRAY[
                   CASE WHEN EXISTS(SELECT 1 FROM hal_documents WHERE publication_id = pub.id) THEN 'HAL' END,
                   CASE WHEN EXISTS(SELECT 1 FROM openalex_documents WHERE publication_id = pub.id) THEN 'OpenAlex' END,
                   CASE WHEN EXISTS(SELECT 1 FROM wos_documents WHERE publication_id = pub.id) THEN 'WoS' END
               ], NULL) AS sources
        FROM authorships a
        JOIN publications pub ON pub.id = a.publication_id
        WHERE a.person_id = %s AND NOT a.excluded
        ORDER BY pub.pub_year DESC NULLS LAST, pub.id DESC
    """, (person_id,))
    publications = [dict(r) for r in cur.fetchall()]

    # Laboratoires associés (via authorships sources)
    cur.execute("""
        SELECT DISTINCT s.id, s.acronym, s.name
        FROM structures s
        WHERE s.structure_type = 'labo' AND s.id IN (
            SELECT UNNEST(has2.structure_ids)
            FROM hal_authors ha2
            JOIN hal_authorships has2 ON has2.hal_author_id = ha2.id
            WHERE ha2.person_id = %s AND has2.structure_ids IS NOT NULL
            UNION ALL
            SELECT UNNEST(oas2.structure_ids)
            FROM openalex_authors oa2
            JOIN openalex_authorships oas2 ON oas2.openalex_author_id = oa2.id
            WHERE oa2.person_id = %s AND oas2.structure_ids IS NOT NULL
        )
        ORDER BY s.acronym NULLS LAST, s.name
    """, (person_id, person_id))
    labs = [{"id": r["id"], "acronym": r["acronym"], "name": r["name"]} for r in cur.fetchall()]

    return {
        "id": person["id"],
        "last_name": person["last_name"],
        "first_name": person["first_name"],
        "last_name_normalized": person["last_name_normalized"],
        "first_name_normalized": person["first_name_normalized"],
        "has_rh": person["has_rh"],
        "role_title": person["role_title"],
        "department_name": person["department_name"],
        "identifiers": identifiers,
        "publications": publications,
        "pub_count": len(publications),
        "labs": labs,
    }


def _parse_skip_pairs(skip: str) -> set[tuple[int, int]]:
    """Parse 'idA-idB,idA-idB,...' en set de tuples."""
    result: set[tuple[int, int]] = set()
    if skip:
        for s in skip.split(","):
            parts = s.strip().split("-")
            if len(parts) == 2:
                try:
                    result.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
    return result


def _scan_dup_query(cur, sql, skip_pairs=None, stop_at_first=False, skip_n=0):
    """Parcourt une requête de doublons avec curseur serveur.
    Retourne (found_row_or_None, count_of_valid_pairs).
    skip_n: nombre de paires valides à sauter avant de retourner la première.
    """
    cur.execute("DECLARE _dup_cur NO SCROLL CURSOR FOR " + sql)
    found = None
    count = 0
    skipped = 0
    while True:
        cur.execute("FETCH 500 FROM _dup_cur")
        rows = cur.fetchall()
        if not rows:
            break
        for row in rows:
            t1 = _person_name_tokens(row["ln1"], row["fn1"])
            t2 = _person_name_tokens(row["ln2"], row["fn2"])
            if not _tokens_match(t1, t2):
                continue
            count += 1
            if found is None:
                # Legacy skip pairs
                if skip_pairs is not None:
                    pair_key = (row["id_a"], row["id_b"])
                    if pair_key in skip_pairs:
                        continue
                # Offset-based skip
                if skipped < skip_n:
                    skipped += 1
                    continue
                found = row
                if stop_at_first:
                    break
        if stop_at_first and found:
            break
    cur.execute("CLOSE _dup_cur")
    return found, count, skipped


# ----- HAL problems: duplicate accounts -----

@router.get("/api/hal-problems/duplicate-accounts")
async def hal_duplicate_accounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Personnes liées à 2+ comptes HAL distincts."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT person_id
                FROM hal_authors
                WHERE person_id IS NOT NULL AND hal_person_id IS NOT NULL
                GROUP BY person_id
                HAVING COUNT(DISTINCT hal_person_id) >= 2
            ) sub
        """)
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT p.id AS person_id, p.last_name, p.first_name,
                   (prh.id IS NOT NULL) AS has_rh,
                   (SELECT json_agg(json_build_object(
                       'hal_person_id', ha.hal_person_id,
                       'full_name', ha.full_name,
                       'idhal', ha.idhal,
                       'orcid', ha.orcid,
                       'pub_count', (SELECT COUNT(*) FROM hal_authorships has2
                                     WHERE has2.hal_author_id = ha.id)
                   ) ORDER BY ha.hal_person_id)
                    FROM hal_authors ha
                    WHERE ha.person_id = p.id AND ha.hal_person_id IS NOT NULL
                   ) AS hal_accounts
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id IN (
                SELECT person_id
                FROM hal_authors
                WHERE person_id IS NOT NULL AND hal_person_id IS NOT NULL
                GROUP BY person_id
                HAVING COUNT(DISTINCT hal_person_id) >= 2
            )
            ORDER BY p.last_name, p.first_name
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        persons = [dict(r) for r in cur.fetchall()]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "persons": persons,
        }


# ----- HAL problems: duplicate publications -----

def _hal_pub_detail(cur, pub_id):
    """Détail d'une publication pour la page doublons HAL."""
    cur.execute("""
        SELECT p.id, p.title, p.pub_year, p.doc_type::text, p.doi, p.container_title
        FROM publications p WHERE p.id = %s
    """, (pub_id,))
    pub = cur.fetchone()
    if not pub:
        return None
    cur.execute("""
        SELECT hd.halid, hd.collections, hd.doc_type AS hal_doc_type, hd.pub_year AS hal_pub_year, hd.title AS hal_title,
               (SELECT COUNT(*) FROM hal_authorships has2 WHERE has2.hal_document_id = hd.id AND NOT has2.excluded) AS author_count
        FROM hal_documents hd WHERE hd.publication_id = %s
    """, (pub_id,))
    hal_docs = [dict(r) for r in cur.fetchall()]
    return {**dict(pub), "hal_docs": hal_docs}


@router.get("/api/hal-problems/duplicate-pubs-doi")
async def hal_duplicate_pubs_by_doi(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT hd.publication_id, LOWER(hd.doi)
                FROM hal_documents hd
                WHERE hd.doi IS NOT NULL AND hd.doi != ''
                GROUP BY hd.publication_id, LOWER(hd.doi)
                HAVING COUNT(*) >= 2
            ) sub
        """)
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT LOWER(hd.doi) AS doi,
                   hd.publication_id AS pub_id,
                   array_agg(hd.halid ORDER BY hd.halid) AS halids
            FROM hal_documents hd
            WHERE hd.doi IS NOT NULL AND hd.doi != ''
            GROUP BY hd.publication_id, LOWER(hd.doi)
            HAVING COUNT(*) >= 2
            ORDER BY LOWER(hd.doi)
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        rows = cur.fetchall()

        pairs = []
        for r in rows:
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


@router.get("/api/hal-problems/duplicate-pubs-meta")
async def hal_duplicate_pubs_by_metadata(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Doublons possibles: dépôts HAL avec métadonnées identiques."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        dup_query = """
            FROM publications p1
            JOIN publications p2 ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
            JOIN hal_documents hd1 ON hd1.publication_id = p1.id
            JOIN hal_documents hd2 ON hd2.publication_id = p2.id
            WHERE LENGTH(p1.title_normalized) > 30
              AND p1.pub_year = p2.pub_year
              AND p1.doc_type = p2.doc_type
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL AND LOWER(p1.doi) <> LOWER(p2.doi))
              AND ABS(
                  (SELECT COUNT(*) FROM hal_authorships ha1 WHERE ha1.hal_document_id = hd1.id AND NOT ha1.excluded)
                  - (SELECT COUNT(*) FROM hal_authorships ha2 WHERE ha2.hal_document_id = hd2.id AND NOT ha2.excluded)
              ) <= 2
              AND NOT EXISTS (SELECT 1 FROM distinct_publications dp
                              WHERE dp.pub_id_a = LEAST(p1.id, p2.id) AND dp.pub_id_b = GREATEST(p1.id, p2.id))
        """

        cur.execute(f"SELECT COUNT(*) {dup_query}")
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT p1.id AS id_a, p2.id AS id_b
            {dup_query}
            ORDER BY p1.id
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        rows = cur.fetchall()

        pairs = []
        for r in rows:
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


# ----- HAL problems: missing collections -----

@router.get("/api/hal-problems/missing-collections")
async def hal_missing_collections(
    lab_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Publications affiliées à un labo sur OA/WoS, présentes dans HAL,
    mais absentes de la collection HAL du labo."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("SELECT acronym, hal_collection FROM structures WHERE id = %s", (lab_id,))
        lab = cur.fetchone()
        if not lab or not lab["hal_collection"]:
            raise HTTPException(status_code=400, detail="Labo sans collection HAL")

        col = lab["hal_collection"]
        lab_arr = [lab_id]

        base_where = """
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id AND a.structure_ids && %s::int[]
            WHERE EXISTS (SELECT 1 FROM hal_documents hd WHERE hd.publication_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM hal_documents hd
                              WHERE hd.publication_id = p.id AND %s = ANY(hd.collections))
        """
        params = [lab_arr, col]

        cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}", params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
                   (SELECT array_agg(hd.halid) FROM hal_documents hd WHERE hd.publication_id = p.id) AS halids,
                   NOT EXISTS (SELECT 1 FROM hal_documents hd
                               WHERE hd.publication_id = p.id AND 'PRES_CLERMONT' = ANY(hd.collections)) AS hors_uca
            {base_where}
            ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
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


@router.get("/api/hal-problems/missing-collections/labs")
async def hal_missing_collections_labs():
    """Liste des labos avec collection HAL."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT s.id, s.acronym, s.name, s.hal_collection
            FROM structures s
            WHERE s.hal_collection IS NOT NULL AND s.structure_type = 'labo'
            ORDER BY s.acronym
        """)
        return [dict(r) for r in cur.fetchall()]


# ----- HAL problems: affiliation conflicts -----

SHS_LAB_CODES = (
    'cmh', 'clerma', 'cerdi', 'chec', 'celis', 'phier', 'ihrim', 'lapsco',
    'comsoc', 'umr_territoires', 'umr_ressources', 'acte', 'lrl', 'lescores', 'msh',
)

def _affiliation_pub_row(r):
    return {
        "id": r["id"], "title": r["title"], "pub_year": r["pub_year"],
        "doc_type": r["doc_type"], "doi": r["doi"],
        "halids": r["halids"], "labs": r["labs"],
    }


@router.get("/api/hal-problems/affiliation-conflicts")
async def hal_affiliation_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Publications affiliées UCA dans HAL mais pas dans OA/WoS."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        base_where = """
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            WHERE a.is_uca = TRUE
              AND a.hal_authorship_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo')
              AND (
                  -- Même position dans OA: adresse présente mais pas UCA
                  EXISTS (
                      SELECT 1 FROM openalex_authorships oas
                      JOIN openalex_documents od ON od.id = oas.openalex_document_id
                      WHERE od.publication_id = p.id
                        AND oas.author_position = a.author_position
                        AND oas.is_uca = FALSE
                        AND oas.raw_affiliation IS NOT NULL AND oas.raw_affiliation != ''
                  )
                  OR EXISTS (
                      SELECT 1 FROM wos_authorships was
                      JOIN wos_documents wd ON wd.id = was.wos_document_id
                      WHERE wd.publication_id = p.id
                        AND was.author_position = a.author_position
                        AND was.is_uca = FALSE
                        AND was.raw_affiliation IS NOT NULL AND was.raw_affiliation != ''
                  )
              )
        """

        cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}")
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
                   (SELECT array_agg(hd.halid) FROM hal_documents hd WHERE hd.publication_id = p.id) AS halids,
                   (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                    FROM structures s WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo') AS labs
            {base_where}
            ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        pubs = [_affiliation_pub_row(r) for r in cur.fetchall()]

        return {
            "total": total, "page": page, "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "publications": pubs,
        }


