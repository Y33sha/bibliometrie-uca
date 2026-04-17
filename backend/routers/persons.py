"""Persons router: directory, search, list, profile, merge, identifiers, authors."""

import logging
import re

from fastapi import APIRouter, HTTPException, Query

from backend.deps import get_cursor
from backend.filters import (
    parse_str_csv,
)
from backend.models import (
    AddIdentifier,
    AssignOrphanAuthorship,
    BatchAssignOrphanAuthorships,
    DetachAuthorships,
    DetachNameForm,
    MergePersons,
    ReassignIdentifier,
    RejectPerson,
    UpdateIdentifierStatus,
    UpdatePersonName,
)
from services.authorships import (
    delete_orphan_authorships as _delete_orphan_authorships,
)
from services.authorships import (
    exclude_authorship as _exclude_authorship,
)
from services.persons import (
    add_identifier as _add_identifier,
)
from services.persons import (
    add_name_form as _add_name_form,
)
from services.persons import (
    assign_orphan_authorship as _assign_orphan,
)
from services.persons import (
    batch_assign_orphan_authorships as _batch_assign_orphan,
)
from services.persons import (
    create_person as _create_person,
)
from services.persons import (
    detach_authorships as _detach_authorships_service,
)
from services.persons import (
    detach_name_form as _detach_name_form,
)
from services.persons import (
    merge_person as _merge_person,
)
from services.persons import (
    reassign_identifier as _reassign_identifier,
)
from services.persons import (
    refresh_person_name_forms as _refresh_person_name_forms,
)
from services.persons import (
    remove_identifier as _remove_identifier,
)
from services.persons import (
    set_rejected as _set_rejected,
)
from services.persons import (
    unlink_authorship as _unlink_authorship,
)
from services.persons import (
    update_identifier_status as _update_identifier_status,
)
from services.persons import (
    update_name as _update_name,
)
from utils.sources import ALL_SOURCES_SET, AUTHOR_SOURCES_SQL

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/persons/directory")
async def persons_directory(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),  # comma-separated
    role: str = Query(""),  # comma-separated
    has_orcid: str = Query(""),  # "yes" or "no"
    has_idhal: str = Query(""),  # "yes" or "no"
    has_rh: str = Query(""),  # "yes" or "no"
    sort: str = Query("name"),  # name, -name
):
    """Annuaire public des personnes UCA avec ORCID et idHAL."""
    offset = (page - 1) * per_page

    departments = [v.strip() for v in department.split(",") if v.strip()] if department else []
    roles = [v.strip() for v in role.split(",") if v.strip()] if role else []

    conditions = ["p.rejected = FALSE"]
    params = []

    if search:
        conditions.append(
            "(unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s))"
        )
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
            "EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')"
        )
    elif has_orcid == "no":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')"
        )
    if has_idhal == "yes":
        conditions.append(
            "EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')"
        )
    elif has_idhal == "no":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')"
        )
    if has_rh == "yes":
        conditions.append("prh.id IS NOT NULL")
    elif has_rh == "no":
        conditions.append("prh.id IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as (cur, conn):
        cur.execute(
            f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}",
            params,
        )
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT
                p.id, p.last_name, p.first_name,
                prh.role_title, prh.department_name,
                (prh.id IS NOT NULL) AS has_rh,
                (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                ) AS orcids,
                (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                ) AS idhals
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            {where}
            ORDER BY {
                {
                    "name": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
                    "-name": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
                }.get(sort, "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC")
            }
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

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
    conditions = ["p.rejected = FALSE"]
    params: list = []
    for w in words:
        s = f"%{w}%"
        conditions.append(
            "(unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s))"
        )
        params.extend([s, s])
    params.append(limit)
    with get_cursor() as (cur, conn):
        cur.execute(
            f"""
            SELECT p.id, p.last_name, p.first_name, prh.department_name,
                   (prh.id IS NOT NULL) AS has_rh
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {" AND ".join(conditions)}
            ORDER BY LOWER(p.last_name), LOWER(p.first_name)
            LIMIT %s
        """,
            params,
        )
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
    has_rh: str = Query(""),  # "yes", "no", ""
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
        conditions.append("EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)")
    elif linked == "no":
        conditions.append("NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)")
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
        cur.execute(
            f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}",
            params,
        )
        total = cur.fetchone()["count"]

        # Requête principale : données personne + counts (rapide)
        cur.execute(
            f"""
            SELECT p.id, p.last_name, p.first_name,
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.rejected,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id AND a.in_perimeter = TRUE) AS uca_pub_count
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            {where}
            ORDER BY {
                {
                    "name": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
                    "-name": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
                    "pubs": "pub_count ASC, LOWER(p.last_name) ASC",
                    "-pubs": "pub_count DESC, LOWER(p.last_name) ASC",
                    "uca_pubs": "uca_pub_count ASC, LOWER(p.last_name) ASC",
                    "-uca_pubs": "uca_pub_count DESC, LOWER(p.last_name) ASC",
                }.get(sort, "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC")
            }
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )
        persons_rows = cur.fetchall()
        person_ids = [p["id"] for p in persons_rows]

        # Identifiants : une seule requête pour les 50 personnes
        identifiers_map: dict = {}
        if person_ids:
            cur.execute(
                """
                SELECT pi.person_id,
                       json_agg(json_build_object(
                           'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                           'source', pi.source, 'status', pi.status
                       ) ORDER BY pi.id_type, pi.id_value) AS identifiers
                FROM person_identifiers pi
                WHERE pi.person_id = ANY(%s)
                GROUP BY pi.person_id
            """,
                (person_ids,),
            )
            for r in cur.fetchall():
                identifiers_map[r["person_id"]] = r["identifiers"]

        # Formes de noms avec sources : depuis person_name_forms
        name_forms_map: dict = {}
        if person_ids:
            cur.execute(
                """
                SELECT pid AS person_id,
                       json_agg(json_build_object(
                           'name_form', pnf.name_form,
                           'sources', pnf.sources,
                           'ambiguous', (array_length(pnf.person_ids, 1) > 1)
                       ) ORDER BY pnf.name_form) AS name_forms
                FROM person_name_forms pnf,
                     LATERAL unnest(pnf.person_ids) AS pid
                WHERE pid = ANY(%s)
                  AND pnf.sources IS NOT NULL
                  AND NOT (pnf.sources = ARRAY['persons']::text[])
                GROUP BY pid
            """,
                (person_ids,),
            )
            for r in cur.fetchall():
                name_forms_map[r["person_id"]] = r["name_forms"]

        # Assembler
        for p in persons_rows:
            p["identifiers"] = identifiers_map.get(p["id"])
            p["name_forms"] = name_forms_map.get(p["id"])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "persons": persons_rows,
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
                conds.append(
                    "EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')"
                )
            elif has_orcid == "no":
                conds.append(
                    "NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected')"
                )
        if skip != "has_idhal":
            if has_idhal == "yes":
                conds.append(
                    "EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')"
                )
            elif has_idhal == "no":
                conds.append(
                    "NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')"
                )
        if skip != "has_rh":
            if has_rh == "yes":
                conds.append("prh.id IS NOT NULL")
            elif has_rh == "no":
                conds.append("prh.id IS NULL")
        if skip != "linked":
            if linked == "yes":
                conds.append("EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)")
            elif linked == "no":
                conds.append("NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)")
        return conds, params

    base_from = "persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id"

    with get_cursor() as (cur, conn):
        # --- Facette DÉPARTEMENTS ---
        c, p = base_filters(skip="department")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(
            f"""
            SELECT prh.department_name AS value, COUNT(*) AS count
            FROM {base_from}
            {where} {"AND" if c else "WHERE"} prh.department_name IS NOT NULL
            GROUP BY prh.department_name ORDER BY count DESC
        """,
            p,
        )
        dept_facets = cur.fetchall()

        # --- Facette RÔLES ---
        c, p = base_filters(skip="role")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(
            f"""
            SELECT prh.role_title AS value, COUNT(*) AS count
            FROM {base_from}
            {where} {"AND" if c else "WHERE"} prh.role_title IS NOT NULL
            GROUP BY prh.role_title ORDER BY count DESC
        """,
            p,
        )
        role_facets = cur.fetchall()

        # --- Facettes booléennes (orcid, idhal, rh) : comptages yes/no ---
        c, p = base_filters(skip="has_orcid")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(
            f"""
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
        """,
            p,
        )
        orcid_counts = cur.fetchone()

        c, p = base_filters(skip="has_idhal")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE
                    EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
                ) AS yes,
                COUNT(*) FILTER (WHERE
                    NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
                ) AS no
            FROM {base_from} {where}
        """,
            p,
        )
        idhal_counts = cur.fetchone()

        c, p = base_filters(skip="has_rh")
        where = ("WHERE " + " AND ".join(c)) if c else ""
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE prh.id IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE prh.id IS NULL) AS no
            FROM {base_from} {where}
        """,
            p,
        )
        rh_counts = cur.fetchone()

        # --- Facette LINKED (admin uniquement) ---
        linked_counts = None
        if linked or True:  # toujours calculer pour que l'admin puisse l'utiliser
            c, p = base_filters(skip="linked")
            where = ("WHERE " + " AND ".join(c)) if c else ""
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE
                        EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)
                    ) AS yes,
                    COUNT(*) FILTER (WHERE
                        NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)
                    ) AS no
                FROM {base_from} {where}
            """,
                p,
            )
            linked_counts = cur.fetchone()

        return {
            "departments": dept_facets,
            "roles": role_facets,
            "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
            "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
            "rh": {"yes": rh_counts["yes"], "no": rh_counts["no"]},
            "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]}
            if linked_counts
            else None,
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
                (SELECT COUNT(*) FROM persons) AS total_persons,
                (SELECT COUNT(DISTINCT person_id) FROM authorships WHERE person_id IS NOT NULL) AS linked_persons,
                (SELECT COUNT(*) FROM authorships WHERE person_id IS NOT NULL) AS linked_authors,
                (SELECT COUNT(DISTINCT department_name)
                 FROM persons_rh WHERE department_name IS NOT NULL) AS departments
        """)
        return cur.fetchone()


@router.get("/api/persons/{person_id}")
async def get_person(person_id: int):
    """Retourne une personne avec ses auteurs lies."""
    with get_cursor() as (cur, conn):
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
        person = cur.fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        return person


@router.get("/api/persons/{person_id}/profile")
async def person_profile(person_id: int):
    """Profil public complet d'une personne : infos, identifiants, auteurs liés."""
    with get_cursor() as (cur, conn):
        # Infos personne
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
            raise HTTPException(status_code=404, detail="Person not found")

        # Identifiants
        cur.execute(
            """
            SELECT id, id_type, id_value, source, status
            FROM person_identifiers WHERE person_id = %s
        """,
            (person_id,),
        )
        identifiers = cur.fetchall()

        # Auteurs liés HAL + compte publis UCA (exclut les authorships rejetées)
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

        # Auteurs liés OpenAlex : formes de noms distinctes
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

        # Auteurs liés WoS + compte publis UCA
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

        # Nombre de thèses avec rôle non-auteur
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


@router.get("/api/persons/{person_id}/theses")
async def person_theses(person_id: int):
    """Thèses liées à cette personne avec un rôle non-auteur (directeur, rapporteur, jury)."""
    with get_cursor() as (cur, conn):
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

        # Collecter tous les structure_ids pour résolution
        all_struct_ids = set()
        for row in rows:
            for sid in row["structure_ids"] or []:
                all_struct_ids.add(sid)

        structures = {}
        if all_struct_ids:
            cur.execute(
                "SELECT id, acronym, name FROM structures WHERE id = ANY(%s)",
                (list(all_struct_ids),),
            )
            for s in cur.fetchall():
                structures[s["id"]] = {"acronym": s["acronym"], "name": s["name"]}

        # Grouper par role
        role_labels = {
            "thesis_director": "Directeur/directrice de thèse",
            "rapporteur": "Rapporteur",
            "jury_president": "Président du jury",
            "jury_member": "Membre du jury",
        }
        by_role: dict[str, list] = {}
        for row in rows:
            roles = row["roles"] or []
            # Prendre le role le plus specifique
            role = "jury_member"
            for r in ("thesis_director", "rapporteur", "jury_president", "jury_member"):
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

        # Ordonner les sections
        sections = []
        for role_key in ("thesis_director", "rapporteur", "jury_president", "jury_member"):
            if role_key in by_role:
                sections.append(
                    {
                        "role": role_key,
                        "label": role_labels.get(role_key, role_key),
                        "theses": by_role[role_key],
                    }
                )

        return {"sections": sections, "total": len(rows), "structures": structures}


@router.get("/api/persons/{person_id}/addresses")
async def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    with get_cursor() as (cur, conn):
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


# ----- Identifier management -----

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@router.post("/api/persons/{person_id}/identifier")
async def add_person_identifier(person_id: int, data: AddIdentifier):
    """Ajoute manuellement un identifiant (ORCID ou idHAL) à une personne."""
    if data.id_type not in ("orcid", "idhal", "idref"):
        raise HTTPException(status_code=400, detail="id_type doit être 'orcid', 'idhal' ou 'idref'")

    id_value = data.id_value.strip()

    # Nettoyage ORCID
    if data.id_type == "orcid":
        id_value = (
            id_value.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
        )
        if not ORCID_RE.match(id_value):
            raise HTTPException(
                status_code=400,
                detail=f"Format ORCID invalide : '{id_value}'. Attendu : 0000-0000-0000-000X",
            )

    if not id_value:
        raise HTTPException(status_code=400, detail="Valeur vide")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        # Vérifier si déjà attribué
        cur.execute(
            "SELECT id, person_id, status::text FROM person_identifiers WHERE id_type = %s AND id_value = %s",
            (data.id_type, id_value),
        )
        existing = cur.fetchone()
        was_reassigned = False
        if existing:
            if existing["person_id"] == person_id:
                return {"added": False, "reason": "already_exists"}
            if existing["status"] != "rejected":
                raise HTTPException(
                    status_code=409,
                    detail=f"Cet identifiant est déjà attribué à la personne #{existing['person_id']}",
                )
            was_reassigned = True

        _add_identifier(cur, person_id, data.id_type, id_value, source="manual")
        result = {"added": True, "id_type": data.id_type, "id_value": id_value}
        if was_reassigned:
            result["reassigned"] = True
        return result


@router.delete("/api/persons/{person_id}/identifier/{id_type}/{id_value:path}")
async def remove_person_identifier(person_id: int, id_type: str, id_value: str):
    """Supprime un identifiant d'une personne."""
    with get_cursor() as (cur, conn):
        if not _remove_identifier(cur, person_id, id_type, id_value):
            raise HTTPException(status_code=404, detail="Identifiant introuvable")
        return {"removed": True}


@router.patch("/api/person-identifiers/{ident_id}/status")
async def update_identifier_status(ident_id: int, body: UpdateIdentifierStatus):
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    with get_cursor() as (cur, conn):
        row = _update_identifier_status(cur, ident_id, body.status)
        if row is None:
            raise HTTPException(status_code=404, detail="Identifiant introuvable")
        return {"id": row["id"], "status": row["status"]}


@router.patch("/api/person-identifiers/{ident_id}/reassign")
async def reassign_identifier(ident_id: int, body: ReassignIdentifier):
    """Réattribue un identifiant rejeté à une autre personne (status → pending)."""
    target_person_id = body.person_id
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (target_person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne cible introuvable")
        if not _reassign_identifier(cur, ident_id, target_person_id):
            raise HTTPException(status_code=404, detail="Identifiant introuvable")
        return {"id": ident_id, "person_id": target_person_id, "status": "pending"}


@router.patch("/api/authorships/{authorship_id}/exclude")
async def toggle_authorship_excluded(authorship_id: int):
    """Marque un authorship comme exclu (lien personne-publication rejeté)."""
    with get_cursor() as (cur, conn):
        row = _exclude_authorship(cur, authorship_id)
        if not row:
            raise HTTPException(status_code=404, detail="Authorship introuvable")
        return {"id": row["id"], "excluded": row["excluded"]}


@router.patch("/api/persons/{person_id}/reject")
async def reject_person(person_id: int, body: RejectPerson):
    """Marque/démarque une personne comme rejetée (fausse entité)."""
    with get_cursor() as (cur, conn):
        if not _set_rejected(cur, person_id, body.rejected):
            raise HTTPException(status_code=404, detail="Personne introuvable")
        return {"ok": True}


@router.patch("/api/persons/{person_id}/name")
async def update_person_name(person_id: int, body: UpdatePersonName):
    """Modifie le nom/prénom d'une personne."""
    last_name = body.last_name.strip()
    first_name = body.first_name.strip()
    if not last_name:
        raise HTTPException(status_code=400, detail="Le nom est requis")
    with get_cursor() as (cur, conn):
        if not _update_name(cur, person_id, last_name, first_name):
            raise HTTPException(status_code=404, detail="Personne introuvable")
        return {"ok": True}


@router.post("/api/persons/{person_id}/merge")
async def merge_persons(person_id: int, body: MergePersons):
    """Fusionne une autre personne (source) dans celle-ci (target)."""
    source_id = body.source_id
    if source_id == person_id:
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


# ----- API: Authorships orphelines -----


# Filtre commun pour les orphan authorships :
# - in_perimeter, sans person_id, sources principales
# - exclut les authorships sur des memoires (etudiants de master)
# - exclut les authorships dont le source_author est rattache a une personne rejetee
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


@router.get("/api/admin/orphan-authorships/count")
async def orphan_authorships_count():
    """Nombre d'authorships UCA sans person_id."""
    with get_cursor() as (cur, conn):
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
        """)
        return cur.fetchone()


@router.get("/api/admin/orphan-authorships")
async def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Liste les authorships UCA sans person_id, avec publication et nom d'auteur."""
    offset = (page - 1) * per_page
    search_cond = ""
    params: list = []
    if search.strip():
        params.append(f"%{search.strip()}%")
        search_cond = "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(%s))"

    with get_cursor() as (cur, conn):
        # Count
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

        # List
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
        rows = cur.fetchall()

        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page or 1,
            "authorships": rows,
        }


# _add_name_form et _ensure_truth_authorship sont dans services.persons


@router.post("/api/admin/orphan-authorships/assign")
async def assign_orphan_authorship_endpoint(body: AssignOrphanAuthorship):
    """Attribue une authorship orpheline à une personne existante ou nouvelle."""
    if body.source not in ALL_SOURCES_SET:
        raise HTTPException(status_code=400, detail=f"Source inconnue: {body.source}")

    person_id = body.person_id
    with get_cursor() as (cur, conn):
        if body.create_person:
            ln = body.create_person.last_name.strip()
            fn = body.create_person.first_name.strip()
            if not ln:
                raise HTTPException(status_code=400, detail="Nom requis")
            person_id = _create_person(cur, ln, fn)
        elif not person_id:
            raise HTTPException(status_code=400, detail="person_id ou create_person requis")

        # Vérifier que la personne existe
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        _assign_orphan(cur, person_id, body.source, body.authorship_id)

        return {"ok": True, "person_id": person_id}


@router.post("/api/admin/orphan-authorships/batch-assign")
async def batch_assign_orphan_authorships(body: BatchAssignOrphanAuthorships):
    """Attribue plusieurs authorships orphelines a une meme personne.

    Fait tout en SQL batch au lieu d'iterer authorship par authorship :
    1. SET person_id sur les source_authorships
    2. Cree les authorships canoniques manquantes
    3. Met les FK source_authorships.authorship_id
    4. Ajoute les formes de noms
    """
    person_id = body.person_id

    sa_ids = [a.authorship_id for a in body.authorships if a.source in ALL_SOURCES_SET]
    if not sa_ids:
        return {"ok": True, "assigned": 0}

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        assigned = _batch_assign_orphan(cur, person_id, sa_ids)
        return {"ok": True, "assigned": assigned}


# ----- API: Formes de noms / détachement authorships -----


@router.get("/api/persons/{person_id}/name-form-authorships")
async def name_form_authorships(person_id: int, name_form: str = Query(...)):
    """Liste les authorships sources liées à une personne pour une forme de nom donnée.
    name_form est la forme normalisée (lowercase, unaccent) depuis person_name_forms.
    Retourne aussi les autres personnes partageant cette forme de nom."""
    with get_cursor() as (cur, conn):
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

        # Autres personnes partageant cette forme de nom
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


@router.post("/api/persons/{person_id}/detach-authorships")
async def detach_authorships(person_id: int, body: DetachAuthorships):
    """Détache des authorships sources d'une personne et nettoie les formes de noms."""
    with get_cursor() as (cur, conn):
        return _detach_authorships_service(
            cur,
            person_id,
            authorships=[{"source": a.source, "authorship_id": a.authorship_id}
                         for a in body.authorships],
            name_form=body.name_form,
        )


@router.post("/api/persons/{person_id}/detach-name-form")
async def detach_name_form(person_id: int, body: DetachNameForm):
    """Détache une forme de nom d'une personne (quand aucune authorship n'y est liée)."""
    name_form = body.name_form

    with get_cursor() as (cur, conn):
        # Vérifier qu'il n'y a aucune authorship liée
        cur.execute(
            f"""
            SELECT COUNT(*) FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.author_name_normalized = %s
              AND sa.source IN {AUTHOR_SOURCES_SQL}
        """,
            (person_id, name_form),
        )
        remaining = cur.fetchone()["count"]
        if remaining > 0:
            raise HTTPException(
                status_code=400, detail="Cette forme a encore des authorships liées"
            )

        _detach_name_form(cur, person_id, name_form)
        return {"detached": True}


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
    cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
               p.last_name_normalized, p.first_name_normalized,
               prh.role_title, prh.department_name,
               (prh.id IS NOT NULL) AS has_rh
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
        SELECT id, id_type, id_value, source, status::text
        FROM person_identifiers WHERE person_id = %s
        ORDER BY id_type, id_value
    """,
        (person_id,),
    )
    identifiers = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT pub.id, pub.title, pub.pub_year, pub.doi, pub.doc_type::text,
               (SELECT array_agg(DISTINCT
                   CASE sd.source
                       WHEN 'hal' THEN 'HAL'
                       WHEN 'openalex' THEN 'OpenAlex'
                       WHEN 'wos' THEN 'WoS'
                       WHEN 'scanr' THEN 'ScanR'
                   END
                ) FROM source_publications sd WHERE sd.publication_id = pub.id
               ) AS sources
        FROM authorships a
        JOIN publications pub ON pub.id = a.publication_id
        WHERE a.person_id = %s AND NOT a.excluded
        ORDER BY pub.pub_year DESC NULLS LAST, pub.id DESC
    """,
        (person_id,),
    )
    publications = [dict(r) for r in cur.fetchall()]

    # Laboratoires associés (via authorships sources)
    cur.execute(
        """
        SELECT DISTINCT s.id, s.acronym, s.name
        FROM structures s
        WHERE s.structure_type = 'labo' AND s.id IN (
            SELECT UNNEST(sa.structure_ids)
            FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.structure_ids IS NOT NULL
        )
        ORDER BY s.acronym NULLS LAST, s.name
    """,
        (person_id,),
    )
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


# ----- HAL problems: duplicate publications -----


def _hal_pub_detail(cur, pub_id):
    """Détail d'une publication pour la page doublons HAL."""
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
        SELECT sd.source_id AS halid, sd.hal_collections, sd.doc_type AS hal_doc_type, sd.pub_year AS hal_pub_year, sd.title AS hal_title,
               (SELECT COUNT(*) FROM source_authorships sa2 WHERE sa2.source = 'hal' AND sa2.source_publication_id = sd.id AND NOT sa2.excluded) AS author_count
        FROM source_publications sd WHERE sd.publication_id = %s AND sd.source = 'hal'
    """,
        (pub_id,),
    )
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
            JOIN source_publications hd1 ON hd1.publication_id = p1.id AND hd1.source = 'hal'
            JOIN source_publications hd2 ON hd2.publication_id = p2.id AND hd2.source = 'hal'
            WHERE LENGTH(p1.title_normalized) > 30
              AND p1.pub_year = p2.pub_year
              AND p1.doc_type = p2.doc_type
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL AND LOWER(p1.doi) <> LOWER(p2.doi))
              AND ABS(
                  (SELECT COUNT(*) FROM source_authorships sa1 WHERE sa1.source = 'hal' AND sa1.source_publication_id = hd1.id AND NOT sa1.excluded)
                  - (SELECT COUNT(*) FROM source_authorships sa2 WHERE sa2.source = 'hal' AND sa2.source_publication_id = hd2.id AND NOT sa2.excluded)
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
            WHERE EXISTS (SELECT 1 FROM source_publications sd WHERE sd.publication_id = p.id AND sd.source = 'hal')
              AND NOT EXISTS (SELECT 1 FROM source_publications sd
                              WHERE sd.publication_id = p.id AND sd.source = 'hal' AND %s = ANY(sd.hal_collections))
        """
        params = [lab_arr, col]

        cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
                   (SELECT array_agg(sd2.source_id) FROM source_publications sd2 WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                   NOT EXISTS (SELECT 1 FROM source_publications sd2
                               WHERE sd2.publication_id = p.id AND sd2.source = 'hal' AND 'PRES_CLERMONT' = ANY(sd2.hal_collections)) AS hors_uca
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
    "cmh",
    "clerma",
    "cerdi",
    "chec",
    "celis",
    "phier",
    "ihrim",
    "lapsco",
    "comsoc",
    "umr_territoires",
    "umr_ressources",
    "acte",
    "lrl",
    "lescores",
    "msh",
)


def _affiliation_pub_row(r):
    return {
        "id": r["id"],
        "title": r["title"],
        "pub_year": r["pub_year"],
        "doc_type": r["doc_type"],
        "doi": r["doi"],
        "halids": r["halids"],
        "labs": r["labs"],
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
            WHERE a.in_perimeter = TRUE
              AND EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'hal')
              AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo')
              AND (
                  -- Même position dans OA: adresse présente mais pas dans le périmètre
                  EXISTS (
                      SELECT 1 FROM source_authorships sa
                      JOIN source_publications sd ON sd.id = sa.source_publication_id
                      WHERE sd.publication_id = p.id
                        AND sa.source = 'openalex'
                        AND sa.author_position = a.author_position
                        AND sa.in_perimeter = FALSE
                        AND EXISTS (SELECT 1 FROM source_authorship_addresses saa WHERE saa.source_authorship_id = sa.id)
                  )
                  OR EXISTS (
                      SELECT 1 FROM source_authorships sa
                      JOIN source_publications sd ON sd.id = sa.source_publication_id
                      WHERE sd.publication_id = p.id
                        AND sa.source = 'wos'
                        AND sa.author_position = a.author_position
                        AND sa.in_perimeter = FALSE
                        AND EXISTS (SELECT 1 FROM source_authorship_addresses saa WHERE saa.source_authorship_id = sa.id)
                  )
              )
        """

        cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}")
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
                   (SELECT array_agg(sd2.source_id) FROM source_publications sd2 WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                   (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                    FROM structures s WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo') AS labs
            {base_where}
            ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )
        pubs = [_affiliation_pub_row(r) for r in cur.fetchall()]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "publications": pubs,
        }
