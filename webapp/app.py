"""
Interface web de revue des adresses (faux positifs).

Vue par adresse : chaque ligne = une adresse distincte, avec le nombre
de publications concernées. Permet de marquer les faux positifs en masse.

Usage:
    cd publisher-stats
    python webapp/app.py

Puis ouvrir http://localhost:8003
"""

import os
import sys
import re
import hashlib
import hmac
import time
import subprocess
import unicodedata
from contextlib import contextmanager

from fastapi import FastAPI, Query, HTTPException, Request, Response, Depends, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DB, ADMIN_USER, ADMIN_SALT, ADMIN_HASH, SESSION_SECRET

app = FastAPI(title="Bibliométrie UCA")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "frontend", "build")


class SPAStaticFiles(StaticFiles):
    """Sert les fichiers statiques avec fallback index.html pour le routage SPA."""
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except Exception:
            return await super().get_response("index.html", scope)


# ----- Auth helpers -----

SESSION_MAX_AGE = 86400 * 7  # 7 jours


def _sign_token(payload: str) -> str:
    """Signe un payload avec HMAC-SHA256."""
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str) -> str | None:
    """Vérifie la signature et retourne le payload, ou None."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    # Vérifier l'expiration
    try:
        parts = payload.split("|")
        ts = int(parts[1])
        if time.time() - ts > SESSION_MAX_AGE:
            return None
    except (IndexError, ValueError):
        return None
    return payload


def _check_password(password: str) -> bool:
    return hashlib.sha256((ADMIN_SALT + password).encode()).hexdigest() == ADMIN_HASH


def require_admin(session: str | None = Cookie(None, alias="session")):
    """Dépendance FastAPI : vérifie que l'utilisateur est authentifié."""
    if not session or not _verify_token(session):
        raise HTTPException(status_code=401, detail="Non authentifié")


class LoginRequest(BaseModel):
    username: str
    password: str


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protège les endpoints d'écriture (POST/PUT/DELETE/PATCH) sauf auth."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        path = request.scope["path"]
        if not path.startswith("/api/auth/"):
            token = request.cookies.get("session")
            if not token or not _verify_token(token):
                return JSONResponse(status_code=401, content={"detail": "Non authentifié"})
    return await call_next(request)


@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    """Strip /bibliometrie prefix pour que les routes /api/* fonctionnent en accès direct."""
    if request.url.path.startswith("/bibliometrie/api/"):
        request.scope["path"] = request.url.path[len("/bibliometrie"):]
    return await call_next(request)


@app.post("/api/auth/login")
async def auth_login(data: LoginRequest, response: Response):
    if data.username != ADMIN_USER or not _check_password(data.password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    payload = f"{ADMIN_USER}|{int(time.time())}"
    token = _sign_token(payload)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return {"ok": True}


@app.get("/api/auth/check")
async def auth_check(session: str | None = Cookie(None, alias="session")):
    if session and _verify_token(session):
        return {"authenticated": True}
    return {"authenticated": False}


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(key="session", path="/")
    return {"ok": True}


# ----- DB helpers -----

@contextmanager
def get_cursor():
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


OA_OPEN_STATUSES = ('gold', 'hybrid', 'bronze', 'green')

# Filtre SQL : la publication a au moins un authorship UCA (source HAL ou OpenAlex)
PUB_IS_UCA = """(
    EXISTS (SELECT 1 FROM hal_documents hd
            JOIN hal_authorships has ON has.hal_document_id = hd.id
            WHERE hd.publication_id = p.id AND has.is_uca = TRUE)
    OR
    EXISTS (SELECT 1 FROM openalex_documents od
            JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
            WHERE od.publication_id = p.id AND oas.is_uca = TRUE)
)"""


def propagate_uca_for_addresses(cur, address_ids: list[int]):
    """Recalcule is_uca sur openalex_authorships et authorships
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    # 1. Trouver les openalex_authorships affectés
    cur.execute("""
        SELECT DISTINCT oaa.openalex_authorship_id
        FROM openalex_authorship_addresses oaa
        WHERE oaa.address_id = ANY(%s)
    """, (address_ids,))
    oas_ids = [r["openalex_authorship_id"] for r in cur.fetchall()]
    if not oas_ids:
        return

    # 2. Périmètre UCA
    cur.execute("""
        SELECT s.id FROM structures s WHERE s.code = 'uca'
        UNION
        SELECT sr.child_id FROM structure_relations sr
        JOIN structures s ON s.id = sr.parent_id
        WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
    """)
    uca_ids = [r["id"] for r in cur.fetchall()]
    if not uca_ids:
        return

    # 3. Recalculer is_uca et structure_ids pour chaque authorship affecté
    # Un authorship est UCA s'il a au moins une adresse liée à une structure UCA
    # ET que l'adresse n'est pas un faux positif
    cur.execute("""
        WITH affected AS (
            SELECT unnest(%s::int[]) AS oas_id
        ),
        uca_per_authorship AS (
            SELECT oaa.openalex_authorship_id AS oas_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM affected af
            JOIN openalex_authorship_addresses oaa ON oaa.openalex_authorship_id = af.oas_id
            JOIN address_structures ast ON ast.address_id = oaa.address_id
            WHERE ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY oaa.openalex_authorship_id
        )
        UPDATE openalex_authorships oas
        SET is_uca = (upa.struct_ids IS NOT NULL),
            structure_ids = upa.struct_ids
        FROM affected af
        LEFT JOIN uca_per_authorship upa ON upa.oas_id = af.oas_id
        WHERE oas.id = af.oas_id
    """, (oas_ids, uca_ids))

    # 4. Propager vers authorships (vérité) pour les person_id résolus
    # Recalcule depuis les DEUX sources (HAL peut maintenir is_uca même si OA perd)
    cur.execute("""
        WITH affected_pubs AS (
            SELECT DISTINCT od.publication_id, oa.person_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            WHERE oas.id = ANY(%s)
              AND od.publication_id IS NOT NULL
              AND oa.person_id IS NOT NULL
        ),
        -- Recalculer is_uca depuis HAL pour ces mêmes (pub, person)
        hal_uca AS (
            SELECT hd.publication_id, ha.person_id,
                   array_agg(DISTINCT sid) AS struct_ids
            FROM affected_pubs ap
            JOIN hal_documents hd ON hd.publication_id = ap.publication_id
            JOIN hal_authorships has ON has.hal_document_id = hd.id
            JOIN hal_authors ha ON ha.id = has.hal_author_id
                AND ha.person_id = ap.person_id,
            LATERAL unnest(has.structure_ids) AS sid
            WHERE has.is_uca = TRUE AND has.structure_ids IS NOT NULL
            GROUP BY hd.publication_id, ha.person_id
        ),
        -- Recalculer is_uca depuis OpenAlex pour ces mêmes (pub, person)
        oa_uca AS (
            SELECT od.publication_id, oa.person_id,
                   oas.structure_ids AS struct_ids
            FROM affected_pubs ap
            JOIN openalex_documents od ON od.publication_id = ap.publication_id
            JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
                AND oa.person_id = ap.person_id
            WHERE oas.is_uca = TRUE AND oas.structure_ids IS NOT NULL
        ),
        merged AS (
            SELECT ap.publication_id, ap.person_id,
                   COALESCE(hu.struct_ids, '{}') || COALESCE(ou.struct_ids, '{}') AS all_structs,
                   (hu.struct_ids IS NOT NULL OR ou.struct_ids IS NOT NULL) AS any_uca
            FROM affected_pubs ap
            LEFT JOIN hal_uca hu ON hu.publication_id = ap.publication_id
                AND hu.person_id = ap.person_id
            LEFT JOIN oa_uca ou ON ou.publication_id = ap.publication_id
                AND ou.person_id = ap.person_id
        )
        UPDATE authorships a
        SET is_uca = m.any_uca,
            structure_ids = NULLIF(
                (SELECT array_agg(DISTINCT x) FROM unnest(m.all_structs) AS x),
                '{}'
            ),
            updated_at = now()
        FROM merged m
        WHERE a.publication_id = m.publication_id
          AND a.person_id = m.person_id
          AND a.person_id IS NOT NULL
    """, (oas_ids,))


def apply_oa_filter(conditions: list, params: list, oa_status: str | None):
    """Ajoute le filtre OA status aux conditions SQL.

    oa_status peut être une ou plusieurs valeurs séparées par des virgules
    (gold, hybrid, bronze, green, closed, unknown),
    ou 'oa' pour tous les statuts open access.
    """
    if not oa_status:
        return
    values = [v.strip() for v in oa_status.split(',') if v.strip()]
    if not values:
        return
    expanded = []
    for v in values:
        if v == 'oa':
            expanded.extend(OA_OPEN_STATUSES)
        else:
            expanded.append(v)
    expanded = list(set(expanded))
    if len(expanded) == 1:
        conditions.append("p.oa_status::text = %s")
        params.append(expanded[0])
    else:
        conditions.append("p.oa_status::text = ANY(%s)")
        params.append(expanded)


def apply_lab_filter(conditions: list, params: list, lab_ids: list[int]):
    """Ajoute le filtre laboratoire via EXISTS sur les authorships."""
    if not lab_ids:
        return
    conditions.append("""
        (
            EXISTS (
                SELECT 1 FROM hal_documents hd
                JOIN hal_authorships has ON has.hal_document_id = hd.id
                WHERE hd.publication_id = p.id
                  AND has.is_uca = TRUE
                  AND has.structure_ids && %s::int[]
            )
            OR
            EXISTS (
                SELECT 1 FROM openalex_documents od
                JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                WHERE od.publication_id = p.id
                  AND oas.is_uca = TRUE
                  AND oas.structure_ids && %s::int[]
            )
        )
    """)
    params.append(lab_ids)
    params.append(lab_ids)


def apply_year_filter(conditions: list, params: list, years: list[int]):
    """Ajoute le filtre année (une ou plusieurs)."""
    if not years:
        return
    conditions.append("p.pub_year = ANY(%s)")
    params.append(years)


def apply_doc_type_filter(conditions: list, params: list, doc_types: list[str]):
    """Ajoute le filtre type de document."""
    if not doc_types:
        return
    conditions.append("p.doc_type::text = ANY(%s)")
    params.append(doc_types)


def apply_source_filter(conditions: list, source_values: list[str]):
    """Ajoute les filtres de source (hal_yes, hal_no, oa_yes, oa_no)."""
    for sv in source_values:
        if sv == "hal_yes":
            conditions.append(
                "EXISTS (SELECT 1 FROM publication_sources ps"
                " WHERE ps.publication_id = p.id AND ps.source = 'hal')"
            )
        elif sv == "hal_no":
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM publication_sources ps"
                " WHERE ps.publication_id = p.id AND ps.source = 'hal')"
            )
        elif sv == "oa_yes":
            conditions.append(
                "EXISTS (SELECT 1 FROM publication_sources ps"
                " WHERE ps.publication_id = p.id AND ps.source = 'openalex')"
            )
        elif sv == "oa_no":
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM publication_sources ps"
                " WHERE ps.publication_id = p.id AND ps.source = 'openalex')"
            )


def apply_publisher_journal_filter(conditions: list, params: list,
                                   publisher_id: int | None, journal_id: int | None):
    """Ajoute les filtres éditeur et revue."""
    if publisher_id:
        conditions.append("""
            EXISTS (SELECT 1 FROM journals j2
                    WHERE j2.id = p.journal_id AND j2.publisher_id = %s)
        """)
        params.append(publisher_id)
    if journal_id:
        conditions.append("p.journal_id = %s")
        params.append(journal_id)


def parse_int_csv(s: str) -> list[int]:
    """Parse une chaîne CSV d'entiers (ex: '1,2,3')."""
    return [int(v) for v in s.split(',') if v.strip()] if s else []


def parse_str_csv(s: str) -> list[str]:
    """Parse une chaîne CSV de strings."""
    return [v.strip() for v in s.split(',') if v.strip()] if s else []


# ----- Pydantic models -----

class ReviewAction(BaseModel):
    structure_id: int
    is_confirmed: bool | None  # True = confirmé, False = rejeté, None = reset


class BatchReviewAction(BaseModel):
    address_ids: list[int]
    structure_id: int
    is_confirmed: bool | None


@app.get("/")
async def root():
    return RedirectResponse("/bibliometrie/stats")


# ----- API: Stats publications -----

@app.get("/api/pub-stats/publishers")
async def publisher_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    oa_status: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Stats d'articles par éditeur."""
    offset = (page - 1) * per_page
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "j.oa_model IS DISTINCT FROM 'repository'",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)
        apply_oa_filter(conditions, params, oa_status)

        if search:
            conditions.append("pub.name ILIKE %s")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT COUNT(DISTINCT pub.id) AS total
            FROM publications p
            JOIN journals j ON j.id = p.journal_id
            JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            SELECT
                pub.id AS publisher_id,
                pub.name AS publisher_name,
                COUNT(DISTINCT p.id) AS pub_count,
                COUNT(DISTINCT j.id) AS journal_count,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
            FROM publications p
            JOIN journals j ON j.id = p.journal_id
            JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where}
            GROUP BY pub.id, pub.name
            ORDER BY COUNT(DISTINCT p.id) DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "publishers": cur.fetchall(),
        }


@app.get("/api/pub-stats/journals")
async def journal_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    oa_status: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Stats d'articles par revue."""
    offset = (page - 1) * per_page
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "j.id IS NOT NULL",
            "p.doc_type IN ('article', 'review')",
            "j.oa_model IS DISTINCT FROM 'repository'",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if search:
            conditions.append("j.title ILIKE %s")
            params.append(f"%{search}%")

        apply_oa_filter(conditions, params, oa_status)

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT COUNT(DISTINCT j.id) AS total
            FROM publications p
            JOIN journals j ON j.id = p.journal_id
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            SELECT
                j.id AS journal_id,
                j.title AS journal_title,
                j.issn,
                j.eissn,
                pub.name AS publisher_name,
                j.is_predatory,
                j.apc_amount,
                COUNT(DISTINCT p.id) AS pub_count,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
            FROM publications p
            JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where}
            GROUP BY j.id, j.title, j.issn, j.eissn, pub.name, j.is_predatory, j.apc_amount
            ORDER BY COUNT(DISTINCT p.id) DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "journals": cur.fetchall(),
        }


@app.get("/api/pub-stats/by-year")
async def stats_by_year(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
):
    """Ventilation par année (pour les graphiques)."""
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        apply_oa_filter(conditions, params, oa_status)

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT
                p.pub_year,
                COUNT(DISTINCT p.id) AS pub_count,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {where}
            GROUP BY p.pub_year
            ORDER BY p.pub_year
        """, params)

        return cur.fetchall()


@app.get("/api/pub-stats/summary")
async def stats_summary(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
):
    """Résumé global."""
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        apply_oa_filter(conditions, params, oa_status)

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT
                COUNT(DISTINCT p.id) AS total_pubs,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown,
                COUNT(DISTINCT j.publisher_id) AS publisher_count,
                COUNT(DISTINCT j.id) AS journal_count
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {where}
        """, params)

        return cur.fetchone()


@app.get("/api/pub-stats/labs")
async def stats_labs(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Stats d'articles par laboratoire."""
    offset = (page - 1) * per_page
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
        params = []

        if lab_ids:
            conditions.append("ps_structs.struct_ids && %s::int[]")
            params.append(lab_ids)

        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        apply_oa_filter(conditions, params, oa_status)

        where = " AND ".join(conditions)

        # CTE: union des structure_ids UCA depuis HAL et OpenAlex
        structs_cte = """
            pub_structs AS (
                SELECT hd.publication_id, has.structure_ids AS struct_ids
                FROM hal_authorships has
                JOIN hal_documents hd ON hd.id = has.hal_document_id
                WHERE has.is_uca = TRUE AND has.structure_ids IS NOT NULL
                  AND hd.publication_id IS NOT NULL
                UNION ALL
                SELECT od.publication_id, oas.structure_ids AS struct_ids
                FROM openalex_authorships oas
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE oas.is_uca = TRUE AND oas.structure_ids IS NOT NULL
                  AND od.publication_id IS NOT NULL
            )
        """

        cur.execute(f"""
            WITH {structs_cte}
            SELECT COUNT(DISTINCT s.id) AS total
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            JOIN pub_structs ps_structs ON ps_structs.publication_id = p.id
            JOIN structures s ON s.id = ANY(ps_structs.struct_ids) AND s.type = 'labo'
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            WITH {structs_cte}
            SELECT
                s.id AS lab_id,
                s.acronym AS lab_acronym,
                s.name AS lab_name,
                COUNT(DISTINCT p.id) AS pub_count,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            JOIN pub_structs ps_structs ON ps_structs.publication_id = p.id
            JOIN structures s ON s.id = ANY(ps_structs.struct_ids) AND s.type = 'labo'
            WHERE {where}
            GROUP BY s.id, s.acronym, s.name
            ORDER BY COUNT(DISTINCT p.id) DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "labs": cur.fetchall(),
        }


@app.get("/api/pub-stats/years")
async def available_years():
    """Années disponibles (validées uniquement)."""
    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        cur.execute(f"""
            SELECT DISTINCT pub_year FROM publications p
            WHERE {PUB_IS_UCA} AND pub_year IS NOT NULL
            ORDER BY pub_year DESC
        """)
        return [r["pub_year"] for r in cur.fetchall()]


@app.get("/api/pub-stats/facets")
async def stats_facets(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
):
    """Facettes dynamiques : retourne les années et labos disponibles
    en tenant compte des filtres croisés (chaque facette exclut son propre filtre)."""
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")

        # Conditions de base (communes à toutes les facettes)
        base_conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]

        # --- Facette ANNÉES (exclut le filtre année, garde les autres) ---
        year_conds = list(base_conditions)
        year_params: list = []
        apply_lab_filter(year_conds, year_params, lab_ids)
        if publisher_id:
            year_conds.append("j.publisher_id = %s")
            year_params.append(publisher_id)
        if journal_id:
            year_conds.append("p.journal_id = %s")
            year_params.append(journal_id)
        apply_oa_filter(year_conds, year_params, oa_status)

        cur.execute(f"""
            SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {" AND ".join(year_conds)}
              AND p.pub_year IS NOT NULL
            GROUP BY p.pub_year
            ORDER BY p.pub_year DESC
        """, year_params)
        year_facets = [{"value": r["pub_year"], "count": r["count"]}
                       for r in cur.fetchall()]

        # --- Facette LABOS (exclut le filtre labo, garde les autres) ---
        lab_conds = list(base_conditions)
        lab_params: list = []
        apply_year_filter(lab_conds, lab_params, years)
        if publisher_id:
            lab_conds.append("j.publisher_id = %s")
            lab_params.append(publisher_id)
        if journal_id:
            lab_conds.append("p.journal_id = %s")
            lab_params.append(journal_id)
        apply_oa_filter(lab_conds, lab_params, oa_status)

        cur.execute(f"""
            WITH uca_pubs AS (
                SELECT DISTINCT p.id
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE {" AND ".join(lab_conds)}
            ),
            pub_structs AS (
                SELECT hd.publication_id, unnest(has.structure_ids) AS struct_id
                FROM hal_authorships has
                JOIN hal_documents hd ON hd.id = has.hal_document_id
                WHERE has.structure_ids IS NOT NULL
                UNION
                SELECT od.publication_id, unnest(oas.structure_ids) AS struct_id
                FROM openalex_authorships oas
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE oas.structure_ids IS NOT NULL
            )
            SELECT s.id, COALESCE(s.acronym, s.name) AS label,
                   COUNT(DISTINCT ps.publication_id) AS count
            FROM pub_structs ps
            JOIN uca_pubs up ON up.id = ps.publication_id
            JOIN structures s ON s.id = ps.struct_id
            WHERE s.type = 'labo'
            GROUP BY s.id, s.acronym, s.name
            ORDER BY count DESC
        """, lab_params)
        lab_facets = [{"value": r["id"], "label": r["label"], "count": r["count"]}
                      for r in cur.fetchall()]

        # --- Facette OA (exclut le filtre OA, garde les autres) ---
        oa_conds = list(base_conditions)
        oa_params: list = []
        apply_year_filter(oa_conds, oa_params, years)
        apply_lab_filter(oa_conds, oa_params, lab_ids)
        if publisher_id:
            oa_conds.append("j.publisher_id = %s")
            oa_params.append(publisher_id)
        if journal_id:
            oa_conds.append("p.journal_id = %s")
            oa_params.append(journal_id)

        cur.execute(f"""
            SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS count
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {" AND ".join(oa_conds)}
              AND p.oa_status IS NOT NULL
            GROUP BY p.oa_status
            ORDER BY count DESC
        """, oa_params)
        oa_facets = [{"value": r["value"], "count": r["count"]}
                     for r in cur.fetchall()]

        return {"years": year_facets, "labs": lab_facets, "oa_statuses": oa_facets}


@app.get("/api/publications/facets")
async def publications_facets(
    year: str = Query(""),
    lab_id: str = Query(""),
    doc_type: str = Query(""),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
):
    """Facettes dynamiques pour la page publications.
    Chaque facette exclut son propre filtre mais applique tous les autres."""
    years = parse_int_csv(year)
    lab_ids = parse_int_csv(lab_id)
    lab_id_parts = parse_str_csv(lab_id)
    lab_none = "none" in lab_id_parts
    lab_ids_clean = [int(v) for v in lab_id_parts if v != "none"] if lab_id_parts else []
    doc_types = parse_str_csv(doc_type)
    source_values = parse_str_csv(source_filter)

    def base_conds_params():
        """Conditions de base : publications UCA."""
        return [PUB_IS_UCA], []

    def add_all_except(conds, params, *, skip: str):
        """Ajoute tous les filtres sauf celui indiqué par skip."""
        if skip != "year":
            apply_year_filter(conds, params, years)
        if skip != "lab":
            if lab_none and not lab_ids_clean:
                conds.append("""
                    NOT EXISTS (
                        SELECT 1 FROM hal_documents hd
                        JOIN hal_authorships has ON has.hal_document_id = hd.id
                        WHERE hd.publication_id = p.id AND has.is_uca = TRUE
                          AND has.structure_ids IS NOT NULL
                          AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(has.structure_ids) AND s.type = 'labo')
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM openalex_documents od
                        JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                        WHERE od.publication_id = p.id AND oas.is_uca = TRUE
                          AND oas.structure_ids IS NOT NULL
                          AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(oas.structure_ids) AND s.type = 'labo')
                    )
                """)
            elif lab_ids_clean:
                apply_lab_filter(conds, params, lab_ids_clean)
        if skip != "doc_type":
            apply_doc_type_filter(conds, params, doc_types)
        if skip != "oa_status":
            apply_oa_filter(conds, params, oa_status)
        if skip != "source":
            apply_source_filter(conds, source_values)
        apply_publisher_journal_filter(conds, params, publisher_id, journal_id)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")

        # --- Facette ANNÉES ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="year")
        cur.execute(f"""
            SELECT p.pub_year AS value, COUNT(*) AS count
            FROM publications p
            WHERE {" AND ".join(c)} AND p.pub_year IS NOT NULL
            GROUP BY p.pub_year ORDER BY p.pub_year DESC
        """, p)
        year_facets = cur.fetchall()

        # --- Facette LABOS ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="lab")
        cur.execute(f"""
            WITH base_pubs AS (
                SELECT p.id FROM publications p WHERE {" AND ".join(c)}
            ),
            pub_structs AS (
                SELECT hd.publication_id, unnest(has.structure_ids) AS struct_id
                FROM hal_authorships has
                JOIN hal_documents hd ON hd.id = has.hal_document_id
                WHERE has.structure_ids IS NOT NULL
                UNION
                SELECT od.publication_id, unnest(oas.structure_ids) AS struct_id
                FROM openalex_authorships oas
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE oas.structure_ids IS NOT NULL
            )
            SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
                   COUNT(DISTINCT ps.publication_id) AS count
            FROM pub_structs ps
            JOIN base_pubs bp ON bp.id = ps.publication_id
            JOIN structures s ON s.id = ps.struct_id
            WHERE s.type = 'labo'
            GROUP BY s.id, s.acronym, s.name
            ORDER BY count DESC
        """, p)
        lab_facets = cur.fetchall()

        # Compter les pubs sans labo
        cur.execute(f"""
            SELECT COUNT(*) AS count FROM publications p
            WHERE {" AND ".join(c)}
              AND NOT EXISTS (
                  SELECT 1 FROM hal_documents hd
                  JOIN hal_authorships has ON has.hal_document_id = hd.id
                  WHERE hd.publication_id = p.id AND has.is_uca = TRUE
                    AND has.structure_ids IS NOT NULL
                    AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(has.structure_ids) AND s.type = 'labo')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM openalex_documents od
                  JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                  WHERE od.publication_id = p.id AND oas.is_uca = TRUE
                    AND oas.structure_ids IS NOT NULL
                    AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(oas.structure_ids) AND s.type = 'labo')
              )
        """, p)
        no_lab_count = cur.fetchone()["count"]

        # --- Facette DOC_TYPE ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="doc_type")
        cur.execute(f"""
            SELECT p.doc_type::text AS value, COUNT(*) AS count
            FROM publications p
            WHERE {" AND ".join(c)} AND p.doc_type IS NOT NULL
            GROUP BY p.doc_type ORDER BY count DESC
        """, p)
        doc_type_facets = cur.fetchall()

        # --- Facette OA_STATUS ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="oa_status")
        cur.execute(f"""
            SELECT p.oa_status::text AS value, COUNT(*) AS count
            FROM publications p
            WHERE {" AND ".join(c)} AND p.oa_status IS NOT NULL
            GROUP BY p.oa_status ORDER BY count DESC
        """, p)
        oa_facets = cur.fetchall()

        return {
            "years": year_facets,
            "labs": lab_facets,
            "no_lab_count": no_lab_count,
            "doc_types": doc_type_facets,
            "oa_statuses": oa_facets,
        }


@app.get("/api/publications/years")
async def all_years():
    """Toutes les années disponibles."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT DISTINCT pub_year FROM publications
            WHERE pub_year IS NOT NULL
            ORDER BY pub_year DESC
        """)
        return [r["pub_year"] for r in cur.fetchall()]


@app.get("/api/publications/export.csv")
async def export_publications_csv(
    search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    sort: str = Query("year_desc"),
    person_id: int | None = Query(None),
):
    """Export CSV des publications (mêmes filtres que list_publications)."""
    import csv
    import io

    years = [int(v) for v in year.split(',') if v.strip()] if year else []
    doc_types = [v.strip() for v in doc_type.split(',') if v.strip()] if doc_type else []
    lab_id_parts_csv = [v.strip() for v in lab_id.split(',') if v.strip()] if lab_id else []
    lab_none = "none" in lab_id_parts_csv
    lab_ids = [int(v) for v in lab_id_parts_csv if v != "none"] if lab_id_parts_csv else []
    oa_values = [v.strip() for v in oa_status.split(',') if v.strip()] if oa_status else []
    source_values = [v.strip() for v in source_filter.split(',') if v.strip()] if source_filter else []

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")

        if person_id:
            conditions = ["""
                (
                    EXISTS (SELECT 1 FROM hal_documents hd
                            JOIN hal_authorships has ON has.hal_document_id = hd.id
                            JOIN hal_authors ha ON ha.id = has.hal_author_id
                            WHERE hd.publication_id = p.id AND ha.person_id = %s)
                    OR
                    EXISTS (SELECT 1 FROM openalex_documents od
                            JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
                            WHERE od.publication_id = p.id AND oa.person_id = %s)
                )
            """]
            params: list = [person_id, person_id]
        elif lab_none and not lab_ids:
            conditions = [PUB_IS_UCA]
            params = []
        elif lab_ids:
            conditions = []
            params = []
        else:
            conditions = [PUB_IS_UCA]
            params = []

        if search:
            conditions.append("p.title ILIKE %s")
            params.append(f"%{search}%")
        if years:
            conditions.append("p.pub_year = ANY(%s)")
            params.append(years)
        if doc_types:
            conditions.append("p.doc_type::text = ANY(%s)")
            params.append(doc_types)
        if lab_none and not lab_ids:
            conditions.append("""
                NOT EXISTS (
                    SELECT 1 FROM hal_documents hd
                    JOIN hal_authorships has ON has.hal_document_id = hd.id
                    WHERE hd.publication_id = p.id
                      AND has.is_uca = TRUE
                      AND has.structure_ids IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM structures s
                          WHERE s.id = ANY(has.structure_ids) AND s.type = 'labo'
                      )
                )
                AND NOT EXISTS (
                    SELECT 1 FROM openalex_documents od
                    JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                    WHERE od.publication_id = p.id
                      AND oas.is_uca = TRUE
                      AND oas.structure_ids IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM structures s
                          WHERE s.id = ANY(oas.structure_ids) AND s.type = 'labo'
                      )
                )
            """)
        elif lab_ids:
            conditions.append("""
                (
                    EXISTS (
                        SELECT 1 FROM hal_documents hd
                        JOIN hal_authorships has ON has.hal_document_id = hd.id
                        WHERE hd.publication_id = p.id
                          AND has.is_uca = TRUE
                          AND has.structure_ids && %s::int[]
                    )
                    OR
                    EXISTS (
                        SELECT 1 FROM openalex_documents od
                        JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                        WHERE od.publication_id = p.id
                          AND oas.is_uca = TRUE
                          AND oas.structure_ids && %s::int[]
                    )
                )
            """)
            params.append(lab_ids)
            params.append(lab_ids)
        if publisher_id:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM journals j2
                    WHERE j2.id = p.journal_id AND j2.publisher_id = %s
                )
            """)
            params.append(publisher_id)
        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)
        if source_values:
            for sv in source_values:
                if sv == "hal_yes":
                    conditions.append(
                        "EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'hal')"
                    )
                elif sv == "hal_no":
                    conditions.append(
                        "NOT EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'hal')"
                    )
                elif sv == "oa_yes":
                    conditions.append(
                        "EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'openalex')"
                    )
                elif sv == "oa_no":
                    conditions.append(
                        "NOT EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'openalex')"
                    )
        if oa_values:
            expanded = []
            for v in oa_values:
                if v == 'oa':
                    expanded.extend(OA_OPEN_STATUSES)
                else:
                    expanded.append(v)
            conditions.append("p.oa_status::text = ANY(%s)")
            params.append(list(set(expanded)))

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        order_map = {
            "year_desc": "p.pub_year DESC, p.title",
            "year_asc": "p.pub_year ASC, p.title",
            "title": "p.title ASC",
            "title_desc": "p.title DESC",
        }
        order = order_map.get(sort, "p.pub_year DESC, p.title")

        cur.execute(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
                p.oa_status::text,
                j.title AS journal_title,
                pub.name AS publisher_name,
                (SELECT ps.source_id FROM publication_sources ps
                 WHERE ps.publication_id = p.id AND ps.source = 'hal' LIMIT 1) AS hal_id,
                (SELECT ps.source_id FROM publication_sources ps
                 WHERE ps.publication_id = p.id AND ps.source = 'openalex' LIMIT 1) AS openalex_id,
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM (
                     SELECT unnest(has3.structure_ids) AS struct_id
                     FROM hal_authorships has3
                     JOIN hal_documents hd3 ON hd3.id = has3.hal_document_id
                     WHERE hd3.publication_id = p.id AND has3.is_uca = TRUE
                       AND has3.structure_ids IS NOT NULL
                     UNION
                     SELECT unnest(oas3.structure_ids) AS struct_id
                     FROM openalex_authorships oas3
                     JOIN openalex_documents od3 ON od3.id = oas3.openalex_document_id
                     WHERE od3.publication_id = p.id AND oas3.is_uca = TRUE
                       AND oas3.structure_ids IS NOT NULL
                 ) src
                 JOIN structures s ON s.id = src.struct_id AND s.type = 'labo'
                ) AS labs
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where_clause}
            ORDER BY {order}
        """, params)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Année", "Titre", "DOI", "Revue", "Éditeur",
            "Laboratoires", "Type", "Voie OA", "HAL", "OpenAlex",
        ])
        for row in cur.fetchall():
            hal_url = f"https://hal.science/{row['hal_id']}" if row["hal_id"] else ""
            oa_url = f"https://openalex.org/{row['openalex_id']}" if row["openalex_id"] else ""
            writer.writerow([
                row["pub_year"] or "",
                row["title"] or "",
                row["doi"] or "",
                row["journal_title"] or "",
                row["publisher_name"] or "",
                row["labs"] or "",
                row["doc_type"] or "",
                row["oa_status"] or "",
                hal_url,
                oa_url,
            ])

    output = buf.getvalue()
    return Response(
        content="\ufeff" + output,  # BOM for Excel UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=publications.csv"},
    )

# ----- API: Publication detail -----

@app.get("/api/publications/{pub_id}")
async def get_publication(pub_id: int):
    """Détail complet d'une publication : métadonnées, sources, authorships."""
    with get_cursor() as (cur, conn):
        # a) Publication + journal + publisher
        cur.execute("""
            SELECT p.id, p.title, p.pub_year, p.doi, p.doc_type::text, p.oa_status::text,
                   p.language, p.container_title,
                   j.id AS journal_id, j.title AS journal_title, j.issn, j.eissn,
                   j.is_predatory AS journal_predatory, j.apc_amount, j.apc_currency,
                   j.oa_model,
                   pub.id AS publisher_id, pub.name AS publisher_name,
                   pub.is_predatory AS publisher_predatory
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE p.id = %s
        """, (pub_id,))
        pub = cur.fetchone()
        if not pub:
            raise HTTPException(status_code=404, detail="Publication not found")

        # b) Sources
        cur.execute("""
            SELECT 'hal' AS source, hd.halid AS source_id, hd.doi, hd.collections
            FROM hal_documents hd WHERE hd.publication_id = %s
            UNION ALL
            SELECT 'openalex', od.openalex_id, od.doi, NULL
            FROM openalex_documents od WHERE od.publication_id = %s
        """, (pub_id, pub_id))
        sources = cur.fetchall()

        # c) Authorships — truth table
        cur.execute("""
            SELECT a.author_position, a.is_uca, a.is_corresponding,
                   a.structure_ids, a.source_hal, a.source_openalex,
                   pe.id AS person_id, pe.last_name, pe.first_name
            FROM authorships a
            JOIN persons pe ON pe.id = a.person_id
            WHERE a.publication_id = %s AND NOT a.excluded
            ORDER BY a.author_position
        """, (pub_id,))
        authorships = cur.fetchall()

        # d) HAL authorships
        cur.execute("""
            SELECT has.author_position, ha.full_name, ha.person_id,
                   has.is_uca, has.structure_ids, has.excluded
            FROM hal_authorships has
            JOIN hal_authors ha ON ha.id = has.hal_author_id
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            WHERE hd.publication_id = %s
            ORDER BY has.author_position
        """, (pub_id,))
        hal_authorships = cur.fetchall()

        # e) OpenAlex authorships
        cur.execute("""
            SELECT oas.author_position, oa.full_name, oa.person_id,
                   oas.is_uca, oas.structure_ids, oas.raw_affiliation, oas.excluded
            FROM openalex_authorships oas
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE od.publication_id = %s
            ORDER BY oas.author_position
        """, (pub_id,))
        oa_authorships = cur.fetchall()

        # f) Resolve all structure_ids → names
        all_struct_ids = set()
        for row in authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])
        for row in hal_authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])
        for row in oa_authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])

        structures = {}
        if all_struct_ids:
            cur.execute("""
                SELECT id, acronym, name, type FROM structures
                WHERE id = ANY(%s)
            """, (list(all_struct_ids),))
            for s in cur.fetchall():
                structures[str(s["id"])] = {
                    "acronym": s["acronym"], "name": s["name"], "type": s["type"]
                }

        return {
            "publication": dict(pub),
            "sources": [dict(s) for s in sources],
            "authorships": [dict(a) for a in authorships],
            "hal_authorships": [dict(a) for a in hal_authorships],
            "openalex_authorships": [dict(a) for a in oa_authorships],
            "structures": structures,
        }


# ----- API: Publications list -----

@app.get("/api/publications")
async def list_publications(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    lab_id: str = Query(""),           # comma-separated ints
    year: str = Query(""),             # comma-separated ints
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),        # comma-separated values
    source_filter: str = Query(""),    # comma-separated: hal_only, oa_only, both
    doc_type: str = Query(""),         # comma-separated values
    sort: str = Query("year_desc"),    # year_desc, year_asc, title
    person_id: int | None = Query(None),
):
    """Liste les publications avec sources, labos, journal."""
    offset = (page - 1) * per_page

    # Parse comma-separated multi-value params
    years = [int(v) for v in year.split(',') if v.strip()] if year else []
    doc_types = [v.strip() for v in doc_type.split(',') if v.strip()] if doc_type else []
    lab_id_parts = [v.strip() for v in lab_id.split(',') if v.strip()] if lab_id else []
    lab_none = "none" in lab_id_parts
    lab_ids = [int(v) for v in lab_id_parts if v != "none"] if lab_id_parts else []
    oa_values = [v.strip() for v in oa_status.split(',') if v.strip()] if oa_status else []
    source_values = [v.strip() for v in source_filter.split(',') if v.strip()] if source_filter else []

    with get_cursor() as (cur, conn):
        # Disable JIT — these queries are too small to benefit, and
        # JIT compilation overhead dominates (>1s for 161 functions).
        cur.execute("SET LOCAL jit = off")

        if person_id:
            # Quand on filtre par personne, on montre TOUTES ses publications
            # (pas seulement UCA)
            conditions = ["""
                (
                    EXISTS (SELECT 1 FROM hal_documents hd
                            JOIN hal_authorships has ON has.hal_document_id = hd.id
                            JOIN hal_authors ha ON ha.id = has.hal_author_id
                            WHERE hd.publication_id = p.id AND ha.person_id = %s)
                    OR
                    EXISTS (SELECT 1 FROM openalex_documents od
                            JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
                            WHERE od.publication_id = p.id AND oa.person_id = %s)
                )
            """]
            params = [person_id, person_id]
        elif lab_none and not lab_ids:
            # "Aucun labo" uniquement
            conditions = [PUB_IS_UCA]
            params = []
        elif lab_ids:
            # lab_id filter already implies is_uca = TRUE, skip PUB_IS_UCA
            conditions = []
            params = []
        else:
            conditions = [PUB_IS_UCA]
            params = []

        if search:
            conditions.append("p.title ILIKE %s")
            params.append(f"%{search}%")

        if years:
            conditions.append("p.pub_year = ANY(%s)")
            params.append(years)

        if doc_types:
            conditions.append("p.doc_type::text = ANY(%s)")
            params.append(doc_types)

        if lab_none and not lab_ids:
            # Aucun labo : publications UCA sans structure de type labo
            conditions.append("""
                NOT EXISTS (
                    SELECT 1 FROM hal_documents hd
                    JOIN hal_authorships has ON has.hal_document_id = hd.id
                    WHERE hd.publication_id = p.id
                      AND has.is_uca = TRUE
                      AND has.structure_ids IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM structures s
                          WHERE s.id = ANY(has.structure_ids) AND s.type = 'labo'
                      )
                )
                AND NOT EXISTS (
                    SELECT 1 FROM openalex_documents od
                    JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                    WHERE od.publication_id = p.id
                      AND oas.is_uca = TRUE
                      AND oas.structure_ids IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM structures s
                          WHERE s.id = ANY(oas.structure_ids) AND s.type = 'labo'
                      )
                )
            """)
        elif lab_ids:
            conditions.append("""
                (
                    EXISTS (
                        SELECT 1 FROM hal_documents hd
                        JOIN hal_authorships has ON has.hal_document_id = hd.id
                        WHERE hd.publication_id = p.id
                          AND has.is_uca = TRUE
                          AND has.structure_ids && %s::int[]
                    )
                    OR
                    EXISTS (
                        SELECT 1 FROM openalex_documents od
                        JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                        WHERE od.publication_id = p.id
                          AND oas.is_uca = TRUE
                          AND oas.structure_ids && %s::int[]
                    )
                )
            """)
            params.append(lab_ids)
            params.append(lab_ids)

        if publisher_id:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM journals j2
                    WHERE j2.id = p.journal_id AND j2.publisher_id = %s
                )
            """)
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        # Source filter: per-source presence/absence (AND logic)
        if source_values:
            for sv in source_values:
                if sv == "hal_yes":
                    conditions.append(
                        "EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'hal')"
                    )
                elif sv == "hal_no":
                    conditions.append(
                        "NOT EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'hal')"
                    )
                elif sv == "oa_yes":
                    conditions.append(
                        "EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'openalex')"
                    )
                elif sv == "oa_no":
                    conditions.append(
                        "NOT EXISTS (SELECT 1 FROM publication_sources ps"
                        " WHERE ps.publication_id = p.id AND ps.source = 'openalex')"
                    )

        # OA filter: expand 'oa' shortcut, then use ANY
        if oa_values:
            expanded = []
            for v in oa_values:
                if v == 'oa':
                    expanded.extend(OA_OPEN_STATUSES)
                else:
                    expanded.append(v)
            conditions.append("p.oa_status::text = ANY(%s)")
            params.append(list(set(expanded)))

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        order_map = {
            "year_desc": "p.pub_year DESC, p.title",
            "year_asc": "p.pub_year ASC, p.title",
            "title": "p.title ASC",
            "title_desc": "p.title DESC",
        }
        order = order_map.get(sort, "p.pub_year DESC, p.title")

        # Count
        cur.execute(f"SELECT COUNT(*) FROM publications p WHERE {where_clause}", params)
        total = cur.fetchone()["count"]

        # Main query
        cur.execute(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
                p.oa_status::text,
                j.title AS journal_title,
                pub.name AS publisher_name,
                -- Sources: HAL and OpenAlex IDs
                (SELECT ps.source_id FROM publication_sources ps
                 WHERE ps.publication_id = p.id AND ps.source = 'hal' LIMIT 1) AS hal_id,
                (SELECT ps.source_id FROM publication_sources ps
                 WHERE ps.publication_id = p.id AND ps.source = 'openalex' LIMIT 1) AS openalex_id,
                -- Labs (aggregated from HAL + OpenAlex sources)
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM (
                     SELECT unnest(has3.structure_ids) AS struct_id
                     FROM hal_authorships has3
                     JOIN hal_documents hd3 ON hd3.id = has3.hal_document_id
                     WHERE hd3.publication_id = p.id AND has3.is_uca = TRUE
                       AND has3.structure_ids IS NOT NULL
                     UNION
                     SELECT unnest(oas3.structure_ids) AS struct_id
                     FROM openalex_authorships oas3
                     JOIN openalex_documents od3 ON od3.id = oas3.openalex_document_id
                     WHERE od3.publication_id = p.id AND oas3.is_uca = TRUE
                       AND oas3.structure_ids IS NOT NULL
                 ) src
                 JOIN structures s ON s.id = src.struct_id AND s.type = 'labo'
                ) AS labs
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where_clause}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        publications = []
        for row in cur.fetchall():
            publications.append({
                "id": row["id"],
                "title": row["title"],
                "pub_year": row["pub_year"],
                "doi": row["doi"],
                "doc_type": row["doc_type"],
                "oa_status": row["oa_status"],
                "journal": row["journal_title"],
                "publisher": row["publisher_name"],
                "hal_id": row["hal_id"],
                "openalex_id": row["openalex_id"],
                "labs": row["labs"],
            })

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "publications": publications,
        }



# ----- API: Adresses -----

@app.get("/api/addresses")
async def list_addresses(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    structure_id: int | None = Query(None),  # structure de travail (défaut = UCA)
    status: str = Query("pending"),  # pending, confirmed, rejected, all
    search: str = Query(""),
    search_mode: str = Query("contains"),  # contains, not_contains
):
    """Liste les adresses liées à une structure, filtrées par is_confirmed."""
    offset = (page - 1) * per_page

    with get_cursor() as (cur, conn):
        # Résoudre la structure de travail (défaut = UCA)
        if structure_id is None:
            cur.execute("SELECT id FROM structures WHERE code = 'uca'")
            row = cur.fetchone()
            structure_id = row["id"] if row else 0

        conditions = [
            "ast_filter.address_id = a.id",
            "ast_filter.structure_id = %s",
        ]
        params = [structure_id]

        # Filtre statut basé sur is_confirmed pour la structure sélectionnée
        if status == "pending":
            conditions.append("ast_filter.is_confirmed IS NULL")
        elif status == "confirmed":
            conditions.append("ast_filter.is_confirmed = TRUE")
        elif status == "rejected":
            conditions.append("ast_filter.is_confirmed = FALSE")
        # status == "all" → pas de filtre sur is_confirmed

        if search:
            if search_mode == "not_contains":
                conditions.append("a.raw_text NOT ILIKE %s")
            else:
                conditions.append("a.raw_text ILIKE %s")
            params.append(f"%{search}%")

        where_clause = " AND ".join(conditions)

        # Count
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM addresses a
            JOIN address_structures ast_filter ON {where_clause}
        """, params)
        total = cur.fetchone()["total"]

        # Fetch with pub count, aggregated structures, is_confirmed for selected structure
        cur.execute(f"""
            SELECT
                a.id,
                a.raw_text,
                ast_filter.is_confirmed,
                (SELECT json_agg(json_build_object(
                            'id', s.id,
                            'name', s.name,
                            'acronym', s.acronym
                        ) ORDER BY COALESCE(s.acronym, s.name))
                 FROM address_structures ast2
                 JOIN structures s ON s.id = ast2.structure_id
                 WHERE ast2.address_id = a.id AND s.type != 'site'
                ) AS structures,
                (SELECT COUNT(DISTINCT od.publication_id)
                 FROM openalex_authorship_addresses oaa
                 JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                 JOIN openalex_documents od ON od.id = oas.openalex_document_id
                 WHERE oaa.address_id = a.id AND od.publication_id IS NOT NULL
                ) AS pub_count
            FROM addresses a
            JOIN address_structures ast_filter ON {where_clause}
            ORDER BY pub_count DESC, a.id
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        rows = cur.fetchall()
        addresses = []
        for row in rows:
            structs = row["structures"] or []
            addresses.append({
                "id": row["id"],
                "raw_text": row["raw_text"],
                "is_confirmed": row["is_confirmed"],
                "structures": structs,
                "pub_count": row["pub_count"],
            })

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": addresses,
        }


@app.get("/api/addresses/{addr_id}/publications")
async def get_address_publications(addr_id: int, limit: int = Query(20)):
    """Récupère un échantillon de publications liées à une adresse."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id, raw_text FROM addresses WHERE id = %s", (addr_id,))
        addr = cur.fetchone()
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")

        cur.execute("""
            SELECT DISTINCT ON (p.id)
                p.id,
                p.title,
                p.pub_year,
                p.doi,
                p.doc_type::text AS doc_type,
                j.title AS journal_title,
                oa.full_name AS author_name,
                od.openalex_id
            FROM openalex_authorship_addresses oaa
            JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN publications p ON p.id = od.publication_id
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE oaa.address_id = %s
              AND od.publication_id IS NOT NULL
            ORDER BY p.id, p.pub_year DESC
            LIMIT %s
        """, (addr_id, limit))

        return {
            "address_id": addr_id,
            "raw_text": addr["raw_text"],
            "publications": cur.fetchall(),
        }


# ----- API: Review -----

@app.post("/api/addresses/{addr_id}/review")
async def review_address(addr_id: int, action: ReviewAction):
    """Confirme, rejette ou reset le lien adresse↔structure."""
    with get_cursor() as (cur, conn):
        cur.execute(
            "SELECT id FROM address_structures WHERE address_id = %s AND structure_id = %s",
            (addr_id, action.structure_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lien adresse-structure introuvable")

        cur.execute(
            "UPDATE address_structures SET is_confirmed = %s WHERE address_id = %s AND structure_id = %s",
            (action.is_confirmed, addr_id, action.structure_id),
        )

        propagate_uca_for_addresses(cur, [addr_id])
        return {"id": addr_id, "structure_id": action.structure_id, "is_confirmed": action.is_confirmed}


@app.post("/api/addresses/batch-review")
async def batch_review(data: BatchReviewAction):
    """Confirme, rejette ou reset le lien adresse↔structure pour un lot d'adresses."""
    with get_cursor() as (cur, conn):
        cur.execute(
            "UPDATE address_structures SET is_confirmed = %s WHERE address_id = ANY(%s) AND structure_id = %s",
            (data.is_confirmed, data.address_ids, data.structure_id),
        )
        updated = cur.rowcount

        propagate_uca_for_addresses(cur, data.address_ids)
        return {"updated": updated}


# ----- API: Feedback / boucle de rétroaction -----

class AssignStructureAction(BaseModel):
    structure_id: int


@app.get("/api/feedback/stats")
async def feedback_stats():
    """Statistiques de qualité de la détection automatique (script resolve_addresses)."""
    with get_cursor() as (cur, conn):
        # "Détectée UCA par le script" = a une address_structures auto
        # pointant vers une structure dans le périmètre UCA
        cur.execute("""
            WITH uca_perimeter AS (
                SELECT s.id FROM structures s WHERE s.code = 'uca'
                UNION
                SELECT sr.child_id FROM structure_relations sr
                JOIN structures s ON s.id = sr.parent_id
                WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
            ),
            addr_flags AS (
                SELECT
                    a.id,
                    EXISTS (
                        SELECT 1 FROM address_structures ast
                        JOIN uca_perimeter up ON up.id = ast.structure_id
                        WHERE ast.address_id = a.id AND ast.is_confirmed = TRUE
                    ) AS manual_valid,
                    EXISTS (
                        SELECT 1 FROM address_structures ast
                        JOIN uca_perimeter up ON up.id = ast.structure_id
                        WHERE ast.address_id = a.id AND ast.is_confirmed = FALSE
                    ) AS manual_rejected,
                    EXISTS (
                        SELECT 1 FROM address_structures ast
                        JOIN uca_perimeter up ON up.id = ast.structure_id
                        WHERE ast.address_id = a.id AND ast.matched_form_id IS NOT NULL
                    ) AS script_detected
                FROM addresses a
                WHERE EXISTS (
                    SELECT 1 FROM address_structures ast
                    JOIN uca_perimeter up ON up.id = ast.structure_id
                    WHERE ast.address_id = a.id
                      AND (ast.is_confirmed IS NOT NULL OR ast.matched_form_id IS NOT NULL)
                )
            )
            SELECT
                COUNT(*) FILTER (WHERE manual_valid OR manual_rejected) AS total_reviewed,
                COUNT(*) FILTER (WHERE script_detected) AS script_detected,
                COUNT(*) FILTER (WHERE manual_valid) AS manual_valid,
                COUNT(*) FILTER (WHERE manual_rejected) AS manual_rejected,
                COUNT(*) FILTER (
                    WHERE manual_valid AND NOT script_detected
                ) AS false_negatives,
                COUNT(*) FILTER (
                    WHERE manual_rejected AND script_detected
                ) AS false_positives,
                COUNT(*) FILTER (
                    WHERE manual_valid AND script_detected
                ) AS concordant_valid,
                COUNT(*) FILTER (
                    WHERE manual_rejected AND NOT script_detected
                ) AS concordant_rejected,
                COUNT(*) FILTER (
                    WHERE NOT manual_valid AND NOT manual_rejected AND script_detected
                ) AS pending
            FROM addr_flags
        """)
        row = cur.fetchone()

        reviewed = (row["concordant_valid"] or 0) + (row["concordant_rejected"] or 0) + \
                   (row["false_negatives"] or 0) + (row["false_positives"] or 0)
        concordant = (row["concordant_valid"] or 0) + (row["concordant_rejected"] or 0)
        row["detection_rate"] = round(concordant / reviewed * 100, 1) if reviewed else None
        row["total_discordant"] = (row["false_negatives"] or 0) + (row["false_positives"] or 0)

        return row


@app.get("/api/feedback/false-negatives")
async def feedback_false_negatives(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Adresses marquées UCA manuellement mais non détectées par le script (resolve_addresses).
    Chaque adresse représente potentiellement une forme de nom manquante."""
    offset = (page - 1) * per_page

    with get_cursor() as (cur, conn):
        # Critère : confirmée UCA manuellement (is_confirmed = TRUE pour une structure UCA)
        # ET aucune détection auto pointant vers le périmètre UCA
        conditions = [
            """EXISTS (
                SELECT 1 FROM address_structures ast
                JOIN (
                    SELECT s.id FROM structures s WHERE s.code = 'uca'
                    UNION
                    SELECT sr.child_id FROM structure_relations sr
                    JOIN structures s ON s.id = sr.parent_id
                    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
                ) uca ON uca.id = ast.structure_id
                WHERE ast.address_id = a.id AND ast.is_confirmed = TRUE
            )""",
            """NOT EXISTS (
                SELECT 1 FROM address_structures ast
                JOIN (
                    SELECT s.id FROM structures s WHERE s.code = 'uca'
                    UNION
                    SELECT sr.child_id FROM structure_relations sr
                    JOIN structures s ON s.id = sr.parent_id
                    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
                ) uca ON uca.id = ast.structure_id
                WHERE ast.address_id = a.id AND ast.matched_form_id IS NOT NULL
            )""",
        ]
        params = []

        if search:
            conditions.append("a.raw_text ILIKE %s")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT COUNT(*) FROM addresses a WHERE {where}
        """, params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT
                a.id,
                a.raw_text,
                (
                    SELECT COUNT(DISTINCT od.publication_id)
                    FROM openalex_authorship_addresses oaa
                    JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                    JOIN openalex_documents od ON od.id = oas.openalex_document_id
                    WHERE oaa.address_id = a.id AND od.publication_id IS NOT NULL
                ) AS pub_count,
                (
                    SELECT json_agg(json_build_object(
                        'structure_id', s.id, 'acronym', s.acronym, 'name', s.name
                    ))
                    FROM address_structures ast
                    JOIN structures s ON s.id = ast.structure_id
                    WHERE ast.address_id = a.id AND s.type != 'site'
                ) AS labs
            FROM addresses a
            WHERE {where}
            ORDER BY (
                SELECT COUNT(DISTINCT od.publication_id)
                FROM openalex_authorship_addresses oaa
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE oaa.address_id = a.id AND od.publication_id IS NOT NULL
            ) DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": cur.fetchall(),
        }


@app.get("/api/feedback/false-positives")
async def feedback_false_positives(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
):
    """Adresses détectées UCA par le script (resolve_addresses) mais rejetées manuellement.
    Le labo auto-détecté indique quelle forme de nom est trop permissive."""
    offset = (page - 1) * per_page

    with get_cursor() as (cur, conn):
        # Critère : rejetée manuellement (is_confirmed = FALSE pour une structure UCA)
        # ET au moins une détection auto pointant vers le périmètre UCA
        conditions = [
            """EXISTS (
                SELECT 1 FROM address_structures ast
                JOIN (
                    SELECT s.id FROM structures s WHERE s.code = 'uca'
                    UNION
                    SELECT sr.child_id FROM structure_relations sr
                    JOIN structures s ON s.id = sr.parent_id
                    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
                ) uca ON uca.id = ast.structure_id
                WHERE ast.address_id = a.id AND ast.is_confirmed = FALSE
            )""",
            """EXISTS (
                SELECT 1 FROM address_structures ast
                JOIN (
                    SELECT s.id FROM structures s WHERE s.code = 'uca'
                    UNION
                    SELECT sr.child_id FROM structure_relations sr
                    JOIN structures s ON s.id = sr.parent_id
                    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
                ) uca ON uca.id = ast.structure_id
                WHERE ast.address_id = a.id AND ast.matched_form_id IS NOT NULL
            )""",
        ]
        params = []

        if search:
            conditions.append("a.raw_text ILIKE %s")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT COUNT(*) FROM addresses a WHERE {where}
        """, params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT
                a.id,
                a.raw_text,
                (
                    SELECT COUNT(DISTINCT od.publication_id)
                    FROM openalex_authorship_addresses oaa
                    JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                    JOIN openalex_documents od ON od.id = oas.openalex_document_id
                    WHERE oaa.address_id = a.id AND od.publication_id IS NOT NULL
                ) AS pub_count,
                (
                    SELECT json_agg(json_build_object(
                        'structure_id', s.id, 'acronym', s.acronym, 'name', s.name
                    ))
                    FROM address_structures ast
                    JOIN structures s ON s.id = ast.structure_id
                    WHERE ast.address_id = a.id AND s.type != 'site'
                ) AS labs,
                (
                    SELECT json_agg(json_build_object(
                        'form_id', nf.id,
                        'form_text', nf.form_text,
                        'requires_context_of', nf.requires_context_of,
                        'structure_code', s.code,
                        'structure_name', COALESCE(s.acronym, s.name)
                    ))
                    FROM address_structures ast
                    JOIN name_forms nf ON nf.id = ast.matched_form_id
                    JOIN structures s ON s.id = nf.structure_id
                    JOIN (
                        SELECT s2.id FROM structures s2 WHERE s2.code = 'uca'
                        UNION
                        SELECT sr2.child_id FROM structure_relations sr2
                        JOIN structures s2 ON s2.id = sr2.parent_id
                        WHERE s2.code = 'uca' AND sr2.relation_type = 'est_tutelle_de'
                    ) uca ON uca.id = ast.structure_id
                    WHERE ast.address_id = a.id AND ast.matched_form_id IS NOT NULL
                ) AS matched_forms
            FROM addresses a
            WHERE {where}
            ORDER BY (
                SELECT COUNT(DISTINCT od.publication_id)
                FROM openalex_authorship_addresses oaa
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE oaa.address_id = a.id AND od.publication_id IS NOT NULL
            ) DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": cur.fetchall(),
        }


@app.post("/api/addresses/{addr_id}/assign-structure")
async def assign_structure(addr_id: int, action: AssignStructureAction):
    """Assigne manuellement une structure à une adresse."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM addresses WHERE id = %s", (addr_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Address not found")

        cur.execute("SELECT id FROM structures WHERE id = %s", (action.structure_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Structure not found")

        # Upsert: insert or update
        cur.execute("""
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (%s, %s, TRUE)
            ON CONFLICT (address_id, structure_id) DO UPDATE
            SET is_confirmed = TRUE
        """, (addr_id, action.structure_id))

        propagate_uca_for_addresses(cur, [addr_id])
        return {"id": addr_id, "structure_id": action.structure_id, "status": "assigned"}


@app.post("/api/feedback/rerun")
async def feedback_rerun():
    """Lance resolve_addresses --rerun."""
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "processing", "resolve_addresses.py")
    if not os.path.exists(script):
        raise HTTPException(status_code=500, detail="Script resolve_addresses.py introuvable")

    try:
        result = subprocess.run(
            [sys.executable, script, "--rerun"],
            capture_output=True, text=True, timeout=300,
        )
        lines = (result.stdout + result.stderr).strip().split("\n")
        summary = [l for l in lines if any(k in l for k in ["Terminé", "UCA", "Affiliat", "Reset"])]
        return {
            "success": result.returncode == 0,
            "summary": summary[-5:] if summary else lines[-5:],
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout (>5min)")


@app.delete("/api/addresses/{addr_id}/assign-structure")
async def unassign_structure(addr_id: int, structure_id: int = Query(...)):
    """Supprime l'assignation manuelle d'une structure."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
        """, (addr_id, structure_id))
        propagate_uca_for_addresses(cur, [addr_id])
        return {"deleted": cur.rowcount > 0}


# ----- API: Labos -----

@app.get("/api/laboratories")
async def list_laboratories():
    """Liste des labos ayant l'UCA pour tutelle."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT s.id, s.code, s.name, s.acronym,
                   s.ror_id, s.hal_collection,
                   (SELECT json_agg(json_build_object(
                       'id', sp.id, 'name', sp.name, 'acronym', sp.acronym, 'type', sp.type::text
                   ) ORDER BY sp.name)
                    FROM structure_relations sr
                    JOIN structures sp ON sp.id = sr.parent_id
                    WHERE sr.child_id = s.id
                      AND sr.relation_type = 'est_tutelle_de'
                      AND sp.code != 'uca'
                   ) AS tutelles
            FROM structures s
            WHERE s.type = 'labo'
              AND EXISTS (
                  SELECT 1 FROM structure_relations sr
                  JOIN structures uca ON uca.id = sr.parent_id AND uca.code = 'uca'
                  WHERE sr.child_id = s.id AND sr.relation_type = 'est_tutelle_de'
              )
            ORDER BY s.name
        """)
        return cur.fetchall()


@app.get("/api/laboratories/{lab_id}")
async def get_laboratory(lab_id: int):
    """Profil public d'un laboratoire."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT s.id, s.code, s.name, s.acronym, s.type::text AS type,
                   s.ror_id, s.rnsr_id, s.hal_collection
            FROM structures s
            WHERE s.id = %s
        """, (lab_id,))
        struct = cur.fetchone()
        if not struct:
            raise HTTPException(404, "Laboratory not found")

        cur.execute("""
            SELECT sp.id, sp.name, sp.acronym, sp.type::text AS type,
                   sr.relation_type
            FROM structure_relations sr
            JOIN structures sp ON sp.id = sr.parent_id
            WHERE sr.child_id = %s
            ORDER BY sr.relation_type, sp.name
        """, (lab_id,))
        parents = cur.fetchall()

        cur.execute("""
            SELECT sc.id, sc.name, sc.acronym, sc.type::text AS type,
                   sr.relation_type
            FROM structure_relations sr
            JOIN structures sc ON sc.id = sr.child_id
            WHERE sr.parent_id = %s
            ORDER BY sc.name
        """, (lab_id,))
        children = cur.fetchall()

        return {
            "structure": struct,
            "parents": parents,
            "children": children,
        }


@app.get("/api/laboratories/{lab_id}/persons")
async def get_laboratory_persons(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Personnes et authorships orphelines liées à un labo."""
    offset = (page - 1) * per_page
    lab_arr = [lab_id]

    with get_cursor() as (cur, conn):
        # ---- Personnes liées (via person_id sur hal/openalex_authors) ----
        cur.execute("""
            WITH author_persons AS (
                SELECT DISTINCT ha.person_id
                FROM hal_authors ha
                JOIN hal_authorships has ON has.hal_author_id = ha.id
                WHERE ha.person_id IS NOT NULL
                  AND has.is_uca = TRUE
                  AND has.structure_ids && %s::int[]
                UNION
                SELECT DISTINCT oa.person_id
                FROM openalex_authors oa
                JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
                WHERE oa.person_id IS NOT NULL
                  AND oas.is_uca = TRUE
                  AND oas.structure_ids && %s::int[]
            )
            SELECT COUNT(*) FROM author_persons
        """, (lab_arr, lab_arr))
        total_persons = cur.fetchone()["count"]

        cur.execute("""
            WITH author_persons AS (
                SELECT DISTINCT ha.person_id
                FROM hal_authors ha
                JOIN hal_authorships has ON has.hal_author_id = ha.id
                WHERE ha.person_id IS NOT NULL
                  AND has.is_uca = TRUE
                  AND has.structure_ids && %s::int[]
                UNION
                SELECT DISTINCT oa.person_id
                FROM openalex_authors oa
                JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
                WHERE oa.person_id IS NOT NULL
                  AND oas.is_uca = TRUE
                  AND oas.structure_ids && %s::int[]
            )
            SELECT p.id, p.last_name, p.first_name,
                   prh.role_title, prh.department_name,
                   (prh.id IS NOT NULL) AS has_rh,
                   (SELECT COUNT(DISTINCT pub.id)
                    FROM publications pub
                    WHERE EXISTS (
                        SELECT 1 FROM hal_documents hd
                        JOIN hal_authorships has2 ON has2.hal_document_id = hd.id
                        JOIN hal_authors ha2 ON ha2.id = has2.hal_author_id
                        WHERE hd.publication_id = pub.id
                          AND ha2.person_id = p.id
                          AND has2.structure_ids && %s::int[]
                    ) OR EXISTS (
                        SELECT 1 FROM openalex_documents od
                        JOIN openalex_authorships oas2 ON oas2.openalex_document_id = od.id
                        JOIN openalex_authors oa2 ON oa2.id = oas2.openalex_author_id
                        WHERE od.publication_id = pub.id
                          AND oa2.person_id = p.id
                          AND oas2.structure_ids && %s::int[]
                    )
                   ) AS pub_count
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            JOIN author_persons ap ON ap.person_id = p.id
            ORDER BY p.last_name, p.first_name
            LIMIT %s OFFSET %s
        """, (lab_arr, lab_arr, lab_arr, lab_arr, per_page, offset))
        persons = cur.fetchall()

        # ---- Authorships orphelines (pas encore liées à une personne) ----
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT DISTINCT ha.id
                FROM hal_authors ha
                JOIN hal_authorships has ON has.hal_author_id = ha.id
                WHERE ha.person_id IS NULL
                  AND has.is_uca = TRUE
                  AND has.structure_ids && %s::int[]
            ) sub
        """, (lab_arr,))
        orphan_hal = cur.fetchone()["count"]

        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT DISTINCT oa.id
                FROM openalex_authors oa
                JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
                WHERE oa.person_id IS NULL
                  AND oas.is_uca = TRUE
                  AND oas.structure_ids && %s::int[]
            ) sub
        """, (lab_arr,))
        orphan_oa = cur.fetchone()["count"]

        return {
            "total_persons": total_persons,
            "page": page,
            "per_page": per_page,
            "pages": (total_persons + per_page - 1) // per_page or 1,
            "persons": persons,
            "orphan_authorships": {
                "hal": orphan_hal,
                "openalex": orphan_oa,
                "total": orphan_hal + orphan_oa,
            },
        }


@app.get("/api/laboratories/{lab_id}/addresses")
async def get_laboratory_addresses(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    """Adresses liées à un laboratoire."""
    offset = (page - 1) * per_page

    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT COUNT(*)
            FROM addresses a
            JOIN address_structures ast ON ast.address_id = a.id
            WHERE ast.structure_id = %s
              AND ast.is_confirmed IS DISTINCT FROM FALSE
        """, (lab_id,))
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT a.id, a.raw_text, ast.is_confirmed
            FROM addresses a
            JOIN address_structures ast ON ast.address_id = a.id
            WHERE ast.structure_id = %s
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            ORDER BY a.raw_text
            LIMIT %s OFFSET %s
        """, (lab_id, per_page, offset))
        addresses = cur.fetchall()

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "addresses": addresses,
        }


@app.get("/api/persons/directory")
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
        conditions.append("(p.last_name ILIKE %s OR p.first_name ILIKE %s)")
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
            "EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected)")
    elif has_orcid == "no":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected)")
    if has_idhal == "yes":
        conditions.append("""(
            EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
            OR EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected)
        )""")
    elif has_idhal == "no":
        conditions.append("""(
            NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
            AND NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected)
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
                (SELECT json_agg(DISTINCT pi.id_value)
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected
                ) AS orcids,
                (SELECT json_agg(DISTINCT v) FROM (
                    SELECT ha.idhal AS v FROM hal_authors ha
                    WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL
                    UNION
                    SELECT pi.id_value FROM person_identifiers pi
                    WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected
                ) sub) AS idhals
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            {where}
            ORDER BY p.last_name, p.first_name
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

@app.get("/api/stats")
async def get_stats(structure_id: int | None = Query(None)):
    """Compteurs de liens adresse↔structure par état de confirmation."""
    with get_cursor() as (cur, conn):
        # Résoudre la structure (défaut = UCA)
        if structure_id is None:
            cur.execute("SELECT id FROM structures WHERE code = 'uca'")
            row = cur.fetchone()
            structure_id = row["id"] if row else 0

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE ast.is_confirmed IS NULL) AS pending,
                COUNT(*) FILTER (WHERE ast.is_confirmed = FALSE) AS rejected,
                COUNT(*) FILTER (WHERE ast.is_confirmed = TRUE) AS confirmed
            FROM address_structures ast
            WHERE ast.structure_id = %s
        """, (structure_id,))
        return cur.fetchone()


# ----- API: Structures CRUD -----

class StructureCreate(BaseModel):
    code: str
    name: str
    acronym: str | None = None
    type: str
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None


class StructureUpdate(BaseModel):
    name: str | None = None
    acronym: str | None = None
    type: str | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None


class RelationCreate(BaseModel):
    parent_id: int
    child_id: int
    relation_type: str


class NameFormCreate(BaseModel):
    structure_id: int
    form_text: str
    is_regex: bool = False
    requires_context_of: list | None = None
    notes: str | None = None


class NameFormUpdate(BaseModel):
    form_text: str | None = None
    is_regex: bool | None = None
    requires_context_of: list | None = None
    is_active: bool | None = None
    notes: str | None = None


@app.get("/api/structures")
async def list_structures(
    type: str | None = Query(None),
    search: str = Query(""),
):
    with get_cursor() as (cur, conn):
        conditions = []
        params = []

        if type:
            conditions.append("s.type::text = %s")
            params.append(type)
        if search:
            conditions.append("(s.name ILIKE %s OR s.acronym ILIKE %s OR s.code ILIKE %s)")
            params.extend([f"%{search}%"] * 3)

        where = " AND ".join(conditions) if conditions else "TRUE"

        cur.execute(f"""
            SELECT s.id, s.code, s.name, s.acronym, s.type::text
            FROM structures s
            WHERE {where}
            ORDER BY s.type, s.name
        """, params)
        return cur.fetchall()


@app.get("/api/structures/{structure_id}")
async def get_structure(structure_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT * FROM structures WHERE id = %s", (structure_id,))
        structure = cur.fetchone()
        if not structure:
            raise HTTPException(status_code=404, detail="Structure not found")

        # Relations : ses tutelles (parents)
        cur.execute("""
            SELECT sr.id AS relation_id, sr.relation_type::text,
                   sp.id, sp.code, sp.name, sp.acronym, sp.type::text AS struct_type
            FROM structure_relations sr
            JOIN structures sp ON sp.id = sr.parent_id
            WHERE sr.child_id = %s
            ORDER BY sr.relation_type, sp.name
        """, (structure_id,))
        parents = cur.fetchall()

        # Relations : ses enfants
        cur.execute("""
            SELECT sr.id AS relation_id, sr.relation_type::text,
                   sc.id, sc.code, sc.name, sc.acronym, sc.type::text AS struct_type
            FROM structure_relations sr
            JOIN structures sc ON sc.id = sr.child_id
            WHERE sr.parent_id = %s
            ORDER BY sr.relation_type, sc.name
        """, (structure_id,))
        children = cur.fetchall()

        # Formes de noms
        cur.execute("""
            SELECT * FROM name_forms
            WHERE structure_id = %s
            ORDER BY is_active DESC, form_text
        """, (structure_id,))
        forms = cur.fetchall()

        return {
            "structure": structure,
            "parents": parents,
            "children": children,
            "forms": forms,
        }


@app.post("/api/structures")
async def create_structure(data: StructureCreate):
    with get_cursor() as (cur, conn):
        cur.execute("""
            INSERT INTO structures (code, name, acronym, type, ror_id, rnsr_id, hal_collection)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (data.code, data.name, data.acronym, data.type,
              data.ror_id, data.rnsr_id, data.hal_collection))
        return cur.fetchone()


@app.put("/api/structures/{structure_id}")
async def update_structure(structure_id: int, data: StructureUpdate):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM structures WHERE id = %s", (structure_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Structure not found")

        updates = []
        params = []
        for field_name in ("name", "acronym", "type", "ror_id", "rnsr_id", "hal_collection"):
            val = getattr(data, field_name, None)
            if val is not None:
                updates.append(f"{field_name} = %s")
                params.append(val)

        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")

        params.append(structure_id)
        cur.execute(f"""
            UPDATE structures SET {', '.join(updates)} WHERE id = %s RETURNING *
        """, params)
        return cur.fetchone()


@app.delete("/api/structures/{structure_id}")
async def delete_structure(structure_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM structures WHERE id = %s", (structure_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Structure not found")
        return {"deleted": True}


@app.post("/api/structure-relations")
async def create_relation(data: RelationCreate):
    with get_cursor() as (cur, conn):
        cur.execute("""
            INSERT INTO structure_relations (parent_id, child_id, relation_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (parent_id, child_id, relation_type) DO NOTHING
            RETURNING *
        """, (data.parent_id, data.child_id, data.relation_type))
        row = cur.fetchone()
        if not row:
            return {"status": "already_exists"}
        return row


@app.delete("/api/structure-relations/{relation_id}")
async def delete_relation(relation_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM structure_relations WHERE id = %s", (relation_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Relation not found")
        return {"deleted": True}


@app.get("/api/name-forms/{form_id}")
async def get_name_form(form_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT * FROM name_forms WHERE id = %s", (form_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Form not found")
        return row


@app.post("/api/name-forms")
async def create_name_form(data: NameFormCreate):
    import json as _json
    with get_cursor() as (cur, conn):
        form_normalized = normalize_text(data.form_text)
        ctx_json = _json.dumps(data.requires_context_of) if data.requires_context_of else None
        cur.execute("""
            INSERT INTO name_forms (structure_id, form_text, form_normalized, is_regex,
                                    requires_context_of, notes)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            RETURNING *
        """, (data.structure_id, data.form_text, form_normalized, data.is_regex,
              ctx_json, data.notes))
        return cur.fetchone()


@app.put("/api/name-forms/{form_id}")
async def update_name_form(form_id: int, data: NameFormUpdate):
    import json as _json
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM name_forms WHERE id = %s", (form_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Name form not found")

        updates = []
        params = []

        if data.form_text is not None:
            updates.append("form_text = %s")
            params.append(data.form_text)
            updates.append("form_normalized = %s")
            params.append(normalize_text(data.form_text))
        if data.is_regex is not None:
            updates.append("is_regex = %s")
            params.append(data.is_regex)
        if data.requires_context_of is not None:
            updates.append("requires_context_of = %s::jsonb")
            params.append(_json.dumps(data.requires_context_of) if data.requires_context_of else None)
        if data.is_active is not None:
            updates.append("is_active = %s")
            params.append(data.is_active)
        if data.notes is not None:
            updates.append("notes = %s")
            params.append(data.notes)

        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")

        params.append(form_id)
        cur.execute(f"""
            UPDATE name_forms SET {', '.join(updates)} WHERE id = %s RETURNING *
        """, params)
        return cur.fetchone()


@app.delete("/api/name-forms/{form_id}")
async def delete_name_form(form_id: int):
    with get_cursor() as (cur, conn):
        cur.execute("DELETE FROM name_forms WHERE id = %s", (form_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Name form not found")
        return {"deleted": True}


# =============================================================
# AUTHORSHIPS (auteurs UCA)
# =============================================================

@app.get("/api/authorships/stats")
async def authorships_stats(lab_id: int = Query(0)):
    """Statistiques auteurs UCA."""
    lab_filter_hal = ""
    lab_filter_oa = ""
    params: list = []
    if lab_id:
        lab_filter_hal = " AND has.structure_ids && %s::int[]"
        lab_filter_oa = " AND oas.structure_ids && %s::int[]"
        params = [[lab_id], [lab_id]]

    with get_cursor() as (cur, conn):
        cur.execute(f"""
            WITH uca_authors AS (
                SELECT ha.id, ha.person_id, ha.orcid, ha.idhal, 'hal' AS source
                FROM hal_authors ha
                WHERE EXISTS (
                    SELECT 1 FROM hal_authorships has
                    WHERE has.hal_author_id = ha.id AND has.is_uca = TRUE{lab_filter_hal}
                )
                UNION ALL
                SELECT oa.id, oa.person_id, oa.orcid, NULL AS idhal, 'openalex' AS source
                FROM openalex_authors oa
                WHERE EXISTS (
                    SELECT 1 FROM openalex_authorships oas
                    WHERE oas.openalex_author_id = oa.id AND oas.is_uca = TRUE{lab_filter_oa}
                )
            )
            SELECT
                COUNT(*) AS total_uca_authors,
                COUNT(*) FILTER (WHERE person_id IS NOT NULL) AS linked_to_person,
                COUNT(*) FILTER (WHERE orcid IS NOT NULL) AS with_orcid,
                COUNT(*) FILTER (WHERE idhal IS NOT NULL) AS with_idhal
            FROM uca_authors
        """, params)
        return cur.fetchone()


@app.get("/api/authorships/facets")
async def authorships_facets(
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
):
    """Facettes dynamiques pour la page authorships admin."""
    lab_filter_hal = ""
    lab_filter_oa = ""
    cte_params: list = []
    if lab_id:
        lab_filter_hal = " AND has.structure_ids && %s::int[]"
        lab_filter_oa = " AND oas.structure_ids && %s::int[]"
        cte_params = [[lab_id], [lab_id]]

    cte = f"""
        WITH uca_authors AS (
            SELECT ha.id, ha.person_id, ha.orcid, ha.idhal, 'hal' AS source,
                   ha.full_name,
                   (SELECT COUNT(DISTINCT hd.publication_id) FROM hal_authorships has2
                    JOIN hal_documents hd ON hd.id = has2.hal_document_id
                    WHERE has2.hal_author_id = ha.id AND has2.is_uca = TRUE) AS uca_pub_count
            FROM hal_authors ha
            WHERE EXISTS (
                SELECT 1 FROM hal_authorships has
                WHERE has.hal_author_id = ha.id AND has.is_uca = TRUE{lab_filter_hal}
            )
            UNION ALL
            SELECT oa.id, oa.person_id, oa.orcid, NULL AS idhal, 'openalex' AS source,
                   oa.full_name,
                   (SELECT COUNT(DISTINCT od.publication_id) FROM openalex_authorships oas2
                    JOIN openalex_documents od ON od.id = oas2.openalex_document_id
                    WHERE oas2.openalex_author_id = oa.id AND oas2.is_uca = TRUE) AS uca_pub_count
            FROM openalex_authors oa
            WHERE EXISTS (
                SELECT 1 FROM openalex_authorships oas
                WHERE oas.openalex_author_id = oa.id AND oas.is_uca = TRUE{lab_filter_oa}
            )
        )
    """

    def build_where(*, skip: str) -> tuple[str, list]:
        conds: list[str] = []
        params: list = []
        if skip != "linked":
            if linked == "yes":
                conds.append("ua.person_id IS NOT NULL")
            elif linked == "no":
                conds.append("ua.person_id IS NULL")
        if skip != "has_orcid":
            if has_orcid == "yes":
                conds.append("ua.orcid IS NOT NULL")
            elif has_orcid == "no":
                conds.append("ua.orcid IS NULL")
        if skip != "has_idhal":
            if has_idhal == "yes":
                conds.append("ua.idhal IS NOT NULL")
            elif has_idhal == "no":
                conds.append("ua.idhal IS NULL")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return where, params

    with get_cursor() as (cur, conn):
        # Linked
        where, p = build_where(skip="linked")
        cur.execute(f"""{cte}
            SELECT
                COUNT(*) FILTER (WHERE ua.person_id IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE ua.person_id IS NULL) AS no
            FROM uca_authors ua {where}
        """, cte_params + p)
        linked_counts = cur.fetchone()

        # ORCID
        where, p = build_where(skip="has_orcid")
        cur.execute(f"""{cte}
            SELECT
                COUNT(*) FILTER (WHERE ua.orcid IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE ua.orcid IS NULL) AS no
            FROM uca_authors ua {where}
        """, cte_params + p)
        orcid_counts = cur.fetchone()

        # idHAL
        where, p = build_where(skip="has_idhal")
        cur.execute(f"""{cte}
            SELECT
                COUNT(*) FILTER (WHERE ua.idhal IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE ua.idhal IS NULL) AS no
            FROM uca_authors ua {where}
        """, cte_params + p)
        idhal_counts = cur.fetchone()

        # Labs (cross-filtered, excluding lab filter itself)
        where, p = build_where(skip="lab")
        # For labs, we need a simplified CTE without lab filter
        lab_cte = f"""
            WITH uca_authors AS (
                SELECT ha.id, ha.person_id, ha.orcid, ha.idhal, 'hal' AS source,
                       ha.full_name
                FROM hal_authors ha
                WHERE EXISTS (
                    SELECT 1 FROM hal_authorships has
                    WHERE has.hal_author_id = ha.id AND has.is_uca = TRUE
                )
                UNION ALL
                SELECT oa.id, oa.person_id, oa.orcid, NULL AS idhal, 'openalex' AS source,
                       oa.full_name
                FROM openalex_authors oa
                WHERE EXISTS (
                    SELECT 1 FROM openalex_authorships oas
                    WHERE oas.openalex_author_id = oa.id AND oas.is_uca = TRUE
                )
            ),
            author_structs AS (
                SELECT ha.id AS author_id, 'hal' AS source, unnest(has.structure_ids) AS struct_id
                FROM hal_authors ha
                JOIN hal_authorships has ON has.hal_author_id = ha.id
                WHERE has.is_uca = TRUE AND has.structure_ids IS NOT NULL
                UNION
                SELECT oa.id, 'openalex', unnest(oas.structure_ids)
                FROM openalex_authors oa
                JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
                WHERE oas.is_uca = TRUE AND oas.structure_ids IS NOT NULL
            )
        """
        cur.execute(f"""{lab_cte}
            SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
                   COUNT(DISTINCT (ast.author_id, ast.source)) AS count
            FROM author_structs ast
            JOIN uca_authors ua ON ua.id = ast.author_id AND ua.source = ast.source
            JOIN structures s ON s.id = ast.struct_id
            {where} {"AND" if where else "WHERE"} s.type = 'labo'
            GROUP BY s.id, s.acronym, s.name
            ORDER BY count DESC
        """, p)
        lab_facets = cur.fetchall()

        return {
            "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]},
            "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
            "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
            "labs": lab_facets,
        }


@app.get("/api/authorships")
async def list_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    linked: str = Query(""),  # "yes", "no", ""
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
):
    """Liste des auteurs UCA avec filtres (UNION hal_authors + openalex_authors)."""
    offset = (page - 1) * per_page

    # Filtre labo (injecté dans le CTE)
    lab_filter_hal = ""
    lab_filter_oa = ""
    cte_params: list = []
    if lab_id:
        lab_filter_hal = " AND has.structure_ids && %s::int[]"
        lab_filter_oa = " AND oas.structure_ids && %s::int[]"
        cte_params = [[lab_id], [lab_id]]

    # Filtres appliqués sur le résultat du CTE
    cte_conditions = []
    params: list = []

    if search:
        cte_conditions.append("(ua.full_name ILIKE %s OR ua.orcid ILIKE %s OR ua.idhal ILIKE %s)")
        s = f"%{search}%"
        params.extend([s, s, s])
    if linked == "yes":
        cte_conditions.append("ua.person_id IS NOT NULL")
    elif linked == "no":
        cte_conditions.append("ua.person_id IS NULL")
    if has_orcid == "yes":
        cte_conditions.append("ua.orcid IS NOT NULL")
    elif has_orcid == "no":
        cte_conditions.append("ua.orcid IS NULL")
    if has_idhal == "yes":
        cte_conditions.append("ua.idhal IS NOT NULL")
    elif has_idhal == "no":
        cte_conditions.append("ua.idhal IS NULL")

    where = ("WHERE " + " AND ".join(cte_conditions)) if cte_conditions else ""

    with get_cursor() as (cur, conn):
        cte = f"""
            WITH uca_authors AS (
                SELECT ha.id, 'hal' AS source, ha.full_name, ha.last_name, ha.first_name,
                       ha.orcid, ha.idhal, NULL::text AS openalex_id, ha.person_id,
                       (SELECT COUNT(DISTINCT has2.hal_document_id)
                        FROM hal_authorships has2
                        WHERE has2.hal_author_id = ha.id AND has2.is_uca = TRUE) AS uca_pub_count
                FROM hal_authors ha
                WHERE EXISTS (
                    SELECT 1 FROM hal_authorships has
                    WHERE has.hal_author_id = ha.id AND has.is_uca = TRUE{lab_filter_hal}
                )
                UNION ALL
                SELECT oa.id, 'openalex' AS source, oa.full_name, oa.last_name, oa.first_name,
                       oa.orcid, NULL::text AS idhal, oa.openalex_id, oa.person_id,
                       (SELECT COUNT(DISTINCT oas2.openalex_document_id)
                        FROM openalex_authorships oas2
                        WHERE oas2.openalex_author_id = oa.id AND oas2.is_uca = TRUE) AS uca_pub_count
                FROM openalex_authors oa
                WHERE EXISTS (
                    SELECT 1 FROM openalex_authorships oas
                    WHERE oas.openalex_author_id = oa.id AND oas.is_uca = TRUE{lab_filter_oa}
                )
            )
        """

        cur.execute(f"""
            {cte}
            SELECT COUNT(*) FROM uca_authors ua {where}
        """, cte_params + params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            {cte}
            SELECT ua.id, ua.source, ua.full_name, ua.last_name, ua.first_name,
                   ua.orcid, ua.idhal, ua.openalex_id, ua.person_id,
                   ua.uca_pub_count,
                   (SELECT json_build_object(
                       'id', p.id, 'last_name', p.last_name,
                       'first_name', p.first_name, 'department_name', prh.department_name,
                       'role_title', prh.role_title,
                       'has_rh', (prh.id IS NOT NULL)
                   ) FROM persons p
                   LEFT JOIN persons_rh prh ON prh.person_id = p.id
                   WHERE p.id = ua.person_id) AS person
            FROM uca_authors ua
            {where}
            ORDER BY ua.uca_pub_count DESC, ua.full_name
            OFFSET %s LIMIT %s
        """, cte_params + params + [offset, per_page])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "authors": cur.fetchall(),
        }


# =============================================================
# PERSONNES (données RH)
# =============================================================

@app.get("/api/persons/search")
async def search_persons(q: str = Query("", min_length=2), limit: int = Query(10, ge=1, le=30)):
    """Recherche rapide de personnes (autocomplete)."""
    s = f"%{q}%"
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT p.id, p.last_name, p.first_name, prh.department_name
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.last_name ILIKE %s OR p.first_name ILIKE %s
            ORDER BY p.last_name, p.first_name
            LIMIT %s
        """, (s, s, limit))
        return cur.fetchall()


@app.get("/api/persons")
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
):
    """Liste des personnes avec filtres."""
    offset = (page - 1) * per_page
    conditions = []
    params = []

    if search:
        conditions.append("""(
            p.last_name ILIKE %s OR p.first_name ILIKE %s
            OR prh.email ILIKE %s OR prh.department_name ILIKE %s
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
            SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id
        ))""")
    elif linked == "no":
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id
        ) AND NOT EXISTS (
            SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id
        )""")
    if has_orcid == "yes":
        conditions.append("""EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected
        )""")
    elif has_orcid == "no":
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected
        )""")
    if has_idhal == "yes":
        conditions.append("""EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected
        )""")
    elif has_idhal == "no":
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected
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
                (SELECT json_agg(x) FROM (
                    SELECT ha.id, ha.full_name, ha.orcid, ha.idhal, 'hal' AS source
                    FROM hal_authors ha WHERE ha.person_id = p.id
                    UNION ALL
                    SELECT oa.id, oa.full_name, oa.orcid, NULL AS idhal, 'openalex' AS source
                    FROM openalex_authors oa WHERE oa.person_id = p.id
                ) x) AS linked_authors,
                (SELECT json_agg(json_build_object(
                    'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                    'source', pi.source, 'rejected', pi.rejected
                )) FROM person_identifiers pi WHERE pi.person_id = p.id
                ) AS identifiers
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            {where}
            ORDER BY p.last_name, p.first_name
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "persons": cur.fetchall(),
        }


@app.get("/api/persons/facets")
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
                conds.append("EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected)")
            elif has_orcid == "no":
                conds.append("NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected)")
        if skip != "has_idhal":
            if has_idhal == "yes":
                conds.append("""(
                    EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    OR EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected)
                )""")
            elif has_idhal == "no":
                conds.append("""(
                    NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    AND NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected)
                )""")
        if skip != "has_rh":
            if has_rh == "yes":
                conds.append("prh.id IS NOT NULL")
            elif has_rh == "no":
                conds.append("prh.id IS NULL")
        if skip != "linked":
            if linked == "yes":
                conds.append("""(EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                    OR EXISTS (SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id))""")
            elif linked == "no":
                conds.append("""NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                    AND NOT EXISTS (SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id)""")
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
                    WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected
                )) AS yes,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM person_identifiers pi
                    WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND NOT pi.rejected
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
                    OR EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected)
                ) AS yes,
                COUNT(*) FILTER (WHERE
                    NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id AND ha.idhal IS NOT NULL)
                    AND NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND NOT pi.rejected)
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
                        OR EXISTS (SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id)
                    ) AS yes,
                    COUNT(*) FILTER (WHERE
                        NOT EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                        AND NOT EXISTS (SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id)
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


@app.get("/api/persons/departments")
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


@app.get("/api/persons/roles")
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


@app.get("/api/persons/stats")
async def persons_stats():
    """Statistiques sur les personnes et l'alignement."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT
                COUNT(*) AS total_persons,
                COUNT(DISTINCT p.id) FILTER (
                    WHERE EXISTS (SELECT 1 FROM hal_authors ha WHERE ha.person_id = p.id)
                       OR EXISTS (SELECT 1 FROM openalex_authors oa WHERE oa.person_id = p.id)
                ) AS linked_persons,
                (SELECT COUNT(*) FROM hal_authors WHERE person_id IS NOT NULL)
                + (SELECT COUNT(*) FROM openalex_authors WHERE person_id IS NOT NULL)
                AS linked_authors,
                (SELECT COUNT(DISTINCT department_name)
                 FROM persons_rh WHERE department_name IS NOT NULL) AS departments
            FROM persons p
        """)
        return cur.fetchone()


@app.get("/api/authors/{source}/{author_id}/details")
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
        else:
            raise HTTPException(status_code=400, detail="Source must be 'hal' or 'openalex'")

        publications = cur.fetchall()
        return {"signatures": [], "publications": publications}


@app.get("/api/persons/{person_id}")
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
                ) x) AS linked_authors,
                (SELECT json_agg(json_build_object(
                    'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                    'source', pi.source, 'rejected', pi.rejected
                )) FROM person_identifiers pi WHERE pi.person_id = p.id
                ) AS identifiers
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = %s
        """, (person_id,))
        person = cur.fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        return person


@app.get("/api/persons/{person_id}/profile")
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
            SELECT id, id_type, id_value, source, rejected
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
            FROM openalex_authors oa WHERE oa.person_id = %s
        """, (person_id,))
        oa_authors = cur.fetchall()

        return {
            "person": person,
            "identifiers": identifiers,
            "authors": hal_authors + oa_authors,
        }


@app.get("/api/persons/{person_id}/addresses")
async def person_addresses(person_id: int):
    """Adresses distinctes utilisées dans les authorships OpenAlex de cette personne."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT a.id, a.raw_text,
                   (SELECT jsonb_agg(jsonb_build_object(
                        'id', s.id, 'acronym', s.acronym, 'name', s.name))
                    FROM address_structures ast
                    JOIN structures s ON s.id = ast.structure_id
                    WHERE ast.address_id = a.id AND s.type != 'site'
                   ) AS structures
            FROM addresses a
            WHERE a.id IN (
                SELECT DISTINCT oaa.address_id
                FROM openalex_authorship_addresses oaa
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
                WHERE oa.person_id = %s
            )
            ORDER BY a.raw_text
        """, (person_id,))
        return cur.fetchall()


@app.get("/api/persons/{person_id}/candidates")
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
            orcid_params = [person_orcid]
        else:
            orcid_cond_hal = ""
            orcid_cond_oa = ""
            orcid_params = []

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
            )
            SELECT * FROM candidates
            WHERE uca_pub_count > 0
            ORDER BY uca_pub_count DESC, pub_count DESC
            LIMIT %s
        """, word_params + orcid_params + word_params + orcid_params + [limit])

        return cur.fetchall()


class LinkPersonAuthor(BaseModel):
    author_id: int
    source: str  # 'hal' or 'openalex'

@app.post("/api/persons/{person_id}/link")
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
                FROM hal_authorships has
                JOIN hal_documents hd ON hd.id = has.hal_document_id
                WHERE has.hal_author_id = %s
                  AND hd.publication_id = ash.publication_id
                  AND ash.source_hal = TRUE
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
                UPDATE openalex_authors SET person_id = %s, updated_at = now()
                WHERE id = %s
            """, (person_id, data.author_id))
            cur.execute("""
                UPDATE authorships ash SET person_id = %s, updated_at = now()
                FROM openalex_authorships oas
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE oas.openalex_author_id = %s
                  AND od.publication_id = ash.publication_id
                  AND ash.source_openalex = TRUE
                  AND ash.person_id IS NULL
            """, (person_id, data.author_id))
            # Propager ORCID vers person_identifiers
            if oa["orcid"]:
                cur.execute("""
                    INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                    VALUES (%s, 'orcid', %s, 'openalex')
                    ON CONFLICT (id_type, id_value) DO NOTHING
                """, (person_id, oa["orcid"]))
        else:
            raise HTTPException(status_code=400, detail="Source must be 'hal' or 'openalex'")

        return {"linked": True, "person_id": person_id,
                "author_id": data.author_id, "source": data.source}


@app.delete("/api/persons/{person_id}/link/{source}/{author_id}")
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
                UPDATE openalex_authors SET person_id = NULL, updated_at = now()
                WHERE id = %s AND person_id = %s
            """, (author_id, person_id))
        else:
            raise HTTPException(status_code=400, detail="Source must be 'hal' or 'openalex'")

        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Link not found")
        return {"unlinked": True}


# ----- Identifier management -----

class AddIdentifier(BaseModel):
    id_type: str   # 'orcid' or 'idhal'
    id_value: str

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@app.post("/api/persons/{person_id}/identifier")
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


@app.delete("/api/persons/{person_id}/identifier/{id_type}/{id_value:path}")
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


@app.patch("/api/person-identifiers/{ident_id}/reject")
async def toggle_reject_identifier(ident_id: int):
    """Bascule le flag rejected d'un identifiant."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            UPDATE person_identifiers SET rejected = NOT rejected
            WHERE id = %s RETURNING id, rejected
        """, (ident_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Identifiant introuvable")
        return {"id": row["id"], "rejected": row["rejected"]}


# ----- SvelteKit SPA (doit rester en dernier, après toutes les routes API) -----

app.mount("/bibliometrie", SPAStaticFiles(directory=BUILD_DIR, html=True), name="sveltekit")


if __name__ == "__main__":
    import uvicorn
    print("Démarrage du serveur sur http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003)
