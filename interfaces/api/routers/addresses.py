"""Auto-extracted router."""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from application import addresses as addresses_service
from interfaces.api.deps import get_cursor, require_admin
from interfaces.api.models import (
    BatchReviewAction,
    BatchSetCountry,
    ReviewAction,
    SetCountry,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _bg_propagate_countries(address_ids: list[int]) -> Any:
    """Propagation pays en tâche de fond (connexion séparée)."""
    from infrastructure.db.connection import get_connection

    try:
        conn = get_connection()
        cur = conn.cursor()
        addresses_service.propagate_countries_to_publications(cur, address_ids)
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        logger.exception("Erreur propagation pays en background")


@router.get("/api/addresses")
async def list_addresses(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    structure_id: int | None = Query(None),  # structure de travail (défaut = UCA)
    detected: str = Query("yes"),  # all, yes, no
    validation: str = Query("pending"),  # all, pending, confirmed, rejected
    search: str = Query(""),
    search_mode: str = Query("contains"),  # contains, not_contains
) -> Any:
    """Liste les adresses avec filtres détection/validation pour une structure."""
    offset = (page - 1) * per_page

    # Mode "non détecté" ou "tous" sans filtre texte → trop large, exiger une recherche
    if detected in ("no", "all") and not search and validation in ("all", "pending"):
        return {
            "total": 0,
            "page": 1,
            "per_page": per_page,
            "pages": 0,
            "addresses": [],
            "requires_search": True,
        }

    with get_cursor() as (cur, conn):
        # Résoudre la structure de travail (défaut = première racine du périmètre)
        if structure_id is None:
            from infrastructure.app_config import _get_from_db

            perim_code = _get_from_db(cur, "perimeter_persons") or "uca"
            cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (perim_code,))
            row = cur.fetchone()
            root_ids = (row["structure_ids"] if isinstance(row, dict) else row[0]) if row else []
            structure_id = root_ids[0] if root_ids else 0

        # Quand detected != "no", on peut utiliser un JOIN (plus rapide)
        use_inner_join = detected == "yes"

        conditions: list[str] = []
        params: list = [structure_id]  # %s n°1 = structure_id pour le JOIN

        # Filtre détection (existence d'un lien auto-détecté)
        if detected == "yes":
            conditions.append("ast_filter.matched_form_id IS NOT NULL")
        elif detected == "no":
            conditions.append("(ast_filter.id IS NULL OR ast_filter.matched_form_id IS NULL)")

        # Filtre validation manuelle
        if validation == "pending":
            if use_inner_join:
                conditions.append("ast_filter.is_confirmed IS NULL")
            else:
                conditions.append("(ast_filter.id IS NULL OR ast_filter.is_confirmed IS NULL)")
        elif validation == "confirmed":
            conditions.append("ast_filter.is_confirmed = TRUE")
        elif validation == "rejected":
            conditions.append("ast_filter.is_confirmed = FALSE")

        if search:
            if search_mode == "not_contains":
                conditions.append("unaccent(a.raw_text) NOT ILIKE unaccent(%s)")
            else:
                conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        where_clause = (" AND " + " AND ".join(conditions)) if conditions else ""
        join_type = "JOIN" if use_inner_join else "LEFT JOIN"

        from_clause = f"""
            FROM addresses a
            {join_type} address_structures ast_filter
                ON ast_filter.address_id = a.id AND ast_filter.structure_id = %s
            WHERE TRUE {where_clause}
        """

        # Count
        cur.execute(f"SELECT COUNT(*) AS total {from_clause}", params)
        total = cur.fetchone()["total"]

        # Fetch paginé — pub_count pré-calculé dans la colonne
        cur.execute(
            f"""
            SELECT a.id, a.raw_text, a.pub_count,
                   ast_filter.is_confirmed,
                   (ast_filter.matched_form_id IS NOT NULL) AS is_detected,
                   (SELECT json_agg(json_build_object(
                               'id', s.id,
                               'name', s.name,
                               'acronym', s.acronym,
                               'is_confirmed', ast2.is_confirmed,
                               'is_detected', (ast2.matched_form_id IS NOT NULL)
                           ) ORDER BY COALESCE(s.acronym, s.name))
                    FROM address_structures ast2
                    JOIN structures s ON s.id = ast2.structure_id
                    WHERE ast2.address_id = a.id AND s.structure_type != 'site'
                   ) AS structures
            {from_clause}
            ORDER BY a.pub_count DESC, a.id
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        rows = cur.fetchall()
        addresses = []
        for row in rows:
            addresses.append(
                {
                    "id": row["id"],
                    "raw_text": row["raw_text"],
                    "is_confirmed": row["is_confirmed"],
                    "is_detected": row["is_detected"] or False,
                    "structures": row["structures"] or [],
                    "pub_count": row["pub_count"],
                }
            )

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": addresses,
        }


@router.get("/api/addresses/{addr_id}/publications")
async def get_address_publications(addr_id: int, limit: int = Query(20)) -> Any:
    """Récupère un échantillon de publications liées à une adresse."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id, raw_text FROM addresses WHERE id = %s", (addr_id,))
        addr = cur.fetchone()
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")

        cur.execute(
            """
            SELECT DISTINCT ON (p.id)
                p.id,
                p.title,
                p.pub_year,
                p.doi,
                p.doc_type::text AS doc_type,
                j.title AS journal_title,
                sa.raw_author_name AS author_name,
                sd.source_id
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE saa.address_id = %s AND sd.publication_id IS NOT NULL
            ORDER BY p.id, p.pub_year DESC
            LIMIT %s
        """,
            (addr_id, limit),
        )

        return {
            "address_id": addr_id,
            "raw_text": addr["raw_text"],
            "publications": cur.fetchall(),
        }


# ----- API: Review -----


@router.post("/api/addresses/{addr_id}/review")
async def review_address(addr_id: int, action: ReviewAction) -> Any:
    """Confirme, rejette ou reset le lien adresse↔structure (upsert)."""
    with get_cursor() as (cur, conn):
        addresses_service.review_structure_link(
            cur, addr_id, action.structure_id, action.is_confirmed
        )

        # Retourner les structures à jour pour mise à jour locale côté client
        cur.execute(
            """
            SELECT json_agg(json_build_object(
                       'id', s.id,
                       'name', s.name,
                       'acronym', s.acronym,
                       'is_confirmed', ast2.is_confirmed,
                       'is_detected', (ast2.matched_form_id IS NOT NULL)
                   ) ORDER BY COALESCE(s.acronym, s.name))
            FROM address_structures ast2
            JOIN structures s ON s.id = ast2.structure_id
            WHERE ast2.address_id = %s AND s.structure_type != 'site'
        """,
            (addr_id,),
        )
        row = cur.fetchone()
        structures = row["json_agg"] if row and row["json_agg"] else []

        # is_confirmed et is_detected relatifs à la structure filtrée
        cur.execute(
            """
            SELECT is_confirmed, (matched_form_id IS NOT NULL) AS is_detected
            FROM address_structures
            WHERE address_id = %s AND structure_id = %s
        """,
            (addr_id, action.structure_id),
        )
        link = cur.fetchone()

        return {
            "id": addr_id,
            "is_confirmed": link["is_confirmed"] if link else None,
            "is_detected": link["is_detected"] if link else False,
            "structures": structures,
        }


@router.post("/api/addresses/batch-review")
async def batch_review(data: BatchReviewAction) -> Any:
    """Confirme, rejette ou reset le lien adresse↔structure pour un lot d'adresses."""
    with get_cursor() as (cur, conn):
        updated = addresses_service.batch_review_structure_link(
            cur, data.address_ids, data.structure_id, data.is_confirmed
        )
        return {"updated": updated}


# ----- API: Countries -----


@router.get("/api/countries")
async def list_countries() -> Any:
    """Liste des pays."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT code, name FROM countries ORDER BY (code = 'xx') DESC, name")
        return cur.fetchall()


@router.get("/api/addresses/countries")
async def addresses_countries(
    search: str = Query(""),
    has_country: str = Query(""),  # "yes", "no", ""
    country_code: str = Query(""),
    suggested_country: str = Query(""),  # filtre par pays suggéré
    suggest: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Liste des adresses pour l'attribution de pays."""
    offset = (page - 1) * per_page
    conditions = []
    params: list = []

    if search:
        conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    if has_country == "yes":
        conditions.append("a.countries IS NOT NULL")
    elif has_country == "no":
        conditions.append("a.countries IS NULL")
    if country_code:
        conditions.append("%s = ANY(a.countries)")
        params.append(country_code)
    if suggested_country:
        conditions.append("%s = ANY(a.suggested_countries)")
        params.append(suggested_country)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    cur_params = list(params)
    with get_cursor() as (cur, conn):
        cur.execute(f"SELECT COUNT(*) FROM addresses a {where}", cur_params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT a.id, a.raw_text, a.countries, a.suggested_countries, a.pub_count
            FROM addresses a
            {where}
            ORDER BY a.pub_count DESC, a.raw_text
            LIMIT %s OFFSET %s
        """,
            cur_params + [per_page, offset],
        )
        addresses = [dict(r) for r in cur.fetchall()]

        # Nettoyer suggested_countries pour le frontend
        for a in addresses:
            sc = a.pop("suggested_countries", None)
            if suggest and not a["countries"] and sc:
                a["suggested_countries"] = [{"code": c.strip(), "count": 1} for c in sc]
            else:
                a["suggested_countries"] = []

        result = {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "addresses": addresses,
        }

        # Facettes: distribution des pays suggérés sur tout le filtre (sans suggested_country)
        if suggest and not suggested_country:
            sug_where = where
            sug_params = list(cur_params)
            # Ajouter filtre: seulement les adresses avec suggestions
            extra = "a.suggested_countries IS NOT NULL"
            if sug_where:
                sug_where += f" AND {extra}"
            else:
                sug_where = f"WHERE {extra}"
            cur.execute(
                f"""
                SELECT c AS code, COUNT(*) AS cnt
                FROM addresses a, unnest(a.suggested_countries) AS c
                {sug_where}
                GROUP BY c ORDER BY cnt DESC LIMIT 20
            """,
                sug_params,
            )
            result["suggestion_facets"] = [
                {"code": r["code"].strip(), "count": r["cnt"]} for r in cur.fetchall()
            ]

        # Facette pays (excluant le filtre country_code, incluant les autres)
        cf_conditions = []
        cf_params: list = []
        if search:
            cf_conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
            cf_params.append(f"%{search}%")
        if has_country == "yes":
            cf_conditions.append("a.countries IS NOT NULL")
        elif has_country == "no":
            cf_conditions.append("a.countries IS NULL")
        if suggested_country:
            cf_conditions.append("%s = ANY(a.suggested_countries)")
            cf_params.append(suggested_country)
        cf_conditions.append("a.countries IS NOT NULL")
        cf_where = "WHERE " + " AND ".join(cf_conditions)
        cur.execute(
            f"""
            SELECT c AS code, COUNT(*) AS cnt
            FROM addresses a, unnest(a.countries) AS c
            {cf_where}
            GROUP BY c ORDER BY cnt DESC
        """,
            cf_params,
        )
        result["country_facets"] = [
            {"code": r["code"].strip(), "count": r["cnt"]} for r in cur.fetchall()
        ]

        return result


@router.get("/api/addresses/suggest-countries")
async def suggest_countries(
    search: str = Query(""),
    _: Any = Depends(require_admin),
) -> Any:
    """Pour un filtre de recherche, renvoie la distribution des pays
    des adresses qui matchent ET qui ont déjà un pays assigné.
    Sert à suggérer un pays pour les adresses sans pays du même filtre."""
    with get_cursor() as (cur, conn):
        where_clause = ""
        params: list = []
        if search.strip():
            where_clause = "WHERE unaccent(a.raw_text) ILIKE unaccent(%s)"
            params = [f"%{search.strip()}%"]

        # Distribution des pays parmi les adresses matchantes qui en ont
        cur.execute(
            f"""
            SELECT c, COUNT(*) AS cnt
            FROM addresses a, unnest(a.countries) AS c
            {where_clause.replace("WHERE", "WHERE a.countries IS NOT NULL AND") if where_clause else "WHERE a.countries IS NOT NULL"}
            GROUP BY c ORDER BY cnt DESC
        """,
            params,
        )
        suggestions = [{"code": r["c"].strip(), "count": r["cnt"]} for r in cur.fetchall()]

        # Nombre d'adresses sans pays dans le même filtre
        no_country_where = (
            where_clause.replace("WHERE", "WHERE countries IS NULL AND")
            if where_clause
            else "WHERE countries IS NULL"
        )
        cur.execute(f"SELECT COUNT(*) FROM addresses a {no_country_where}", params)
        without_country = cur.fetchone()["count"]

        return {"suggestions": suggestions, "without_country": without_country}


@router.post("/api/addresses/{addr_id}/country")
async def set_address_country(
    addr_id: int, body: SetCountry, bg: BackgroundTasks, _: Any = Depends(require_admin)
) -> Any:
    """Attribue des pays à une adresse."""
    countries = body.countries
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM addresses WHERE id = %s", (addr_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Adresse introuvable")
        if countries:
            for c in countries:
                cur.execute("SELECT code FROM countries WHERE code = %s", (c,))
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail=f"Code pays inconnu: {c}")
        affected = addresses_service.set_country(cur, addr_id, countries)
    # Propager vers documents et publications en background
    bg.add_task(_bg_propagate_countries, affected)
    return {"ok": True}


@router.post("/api/addresses/batch-country")
async def batch_set_country(
    body: BatchSetCountry, bg: BackgroundTasks, _: Any = Depends(require_admin)
) -> Any:
    """Ajoute un pays à des adresses — par IDs ou par filtre."""
    country_code = body.country_code
    if not country_code:
        raise HTTPException(status_code=400, detail="country_code requis")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT code FROM countries WHERE code = %s", (country_code,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Code pays inconnu: {country_code}")

        if body.address_ids:
            modified_ids = addresses_service.batch_set_country_by_ids(
                cur, country_code, body.address_ids
            )
        else:
            modified_ids = addresses_service.batch_set_country_by_filter(
                cur,
                country_code,
                search=body.search,
                has_country=body.has_country,
                country_code_filter=body.country_code_filter,
                suggested_country=body.suggested_country,
            )
        updated = len(modified_ids)

        propagated_ids = addresses_service.propagate_countries_to_similar(cur)
        propagated = len(propagated_ids)
        all_ids = modified_ids + propagated_ids

    # Propager vers documents et publications en background
    bg.add_task(_bg_propagate_countries, all_ids)
    return {"updated": updated, "propagated": propagated}


# ----- API: Feedback / boucle de rétroaction -----
