"""Query services async pour /api/addresses/* et /api/countries (§2.12)."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AddressListFilters:
    detected: str = "yes"  # all, yes, no
    validation: str = "pending"  # all, pending, confirmed, rejected
    search: str = ""
    search_mode: str = "contains"  # contains, not_contains


async def resolve_default_structure_id(cur: Any) -> int:
    """Résout la structure de travail par défaut (première racine du périmètre)."""
    from infrastructure.app_config import _async_get_from_db

    perim_code = await _async_get_from_db(cur, "perimeter_persons") or "uca"
    await cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (perim_code,))
    row = await cur.fetchone()
    root_ids = (row["structure_ids"] if isinstance(row, dict) else row[0]) if row else []
    return root_ids[0] if root_ids else 0


async def list_addresses(
    cur: Any,
    *,
    structure_id: int,
    filters: AddressListFilters,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Liste paginée des adresses avec filtres détection/validation pour une structure."""
    offset = (page - 1) * per_page
    use_inner_join = filters.detected == "yes"

    conditions: list[str] = []
    params: list[Any] = [structure_id]

    if filters.detected == "yes":
        conditions.append("ast_filter.matched_form_id IS NOT NULL")
    elif filters.detected == "no":
        conditions.append("(ast_filter.id IS NULL OR ast_filter.matched_form_id IS NULL)")

    if filters.validation == "pending":
        if use_inner_join:
            conditions.append("ast_filter.is_confirmed IS NULL")
        else:
            conditions.append("(ast_filter.id IS NULL OR ast_filter.is_confirmed IS NULL)")
    elif filters.validation == "confirmed":
        conditions.append("ast_filter.is_confirmed = TRUE")
    elif filters.validation == "rejected":
        conditions.append("ast_filter.is_confirmed = FALSE")

    if filters.search:
        op = "NOT ILIKE" if filters.search_mode == "not_contains" else "ILIKE"
        conditions.append(f"unaccent(a.raw_text) {op} unaccent(%s)")
        params.append(f"%{filters.search}%")

    where_clause = (" AND " + " AND ".join(conditions)) if conditions else ""
    join_type = "JOIN" if use_inner_join else "LEFT JOIN"

    from_clause = f"""
        FROM addresses a
        {join_type} address_structures ast_filter
            ON ast_filter.address_id = a.id AND ast_filter.structure_id = %s
        WHERE TRUE {where_clause}
    """

    await cur.execute(f"SELECT COUNT(*) AS total {from_clause}", params)
    total = (await cur.fetchone())["total"]

    await cur.execute(
        f"""
        SELECT a.id, a.raw_text, a.pub_count,
               ast_filter.is_confirmed,
               (ast_filter.matched_form_id IS NOT NULL) AS is_detected,
               (SELECT json_agg(json_build_object(
                           'id', s.id, 'name', s.name, 'acronym', s.acronym,
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

    addresses = [
        {
            "id": r["id"],
            "raw_text": r["raw_text"],
            "is_confirmed": r["is_confirmed"],
            "is_detected": r["is_detected"] or False,
            "structures": r["structures"] or [],
            "pub_count": r["pub_count"],
        }
        for r in await cur.fetchall()
    ]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "addresses": addresses,
    }


async def get_address_basic(cur: Any, addr_id: int) -> dict[str, Any] | None:
    """Récupère id + raw_text d'une adresse (None si absente)."""
    await cur.execute("SELECT id, raw_text FROM addresses WHERE id = %s", (addr_id,))
    return await cur.fetchone()


async def get_address_publications(cur: Any, addr_id: int, limit: int) -> list[dict[str, Any]]:
    """Publications liées à une adresse (échantillon)."""
    await cur.execute(
        """
        SELECT DISTINCT ON (p.id)
            p.id, p.title, p.pub_year, p.doi,
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
    return await cur.fetchall()


async def get_address_structures(cur: Any, addr_id: int) -> list[dict[str, Any]]:
    """Structures liées à une adresse (pour rafraîchir le client après review)."""
    await cur.execute(
        """
        SELECT json_agg(json_build_object(
                   'id', s.id, 'name', s.name, 'acronym', s.acronym,
                   'is_confirmed', ast2.is_confirmed,
                   'is_detected', (ast2.matched_form_id IS NOT NULL)
               ) ORDER BY COALESCE(s.acronym, s.name))
        FROM address_structures ast2
        JOIN structures s ON s.id = ast2.structure_id
        WHERE ast2.address_id = %s AND s.structure_type != 'site'
        """,
        (addr_id,),
    )
    row = await cur.fetchone()
    return row["json_agg"] if row and row["json_agg"] else []


async def get_structure_link(
    cur: Any, addr_id: int, structure_id: int
) -> dict[str, Any] | None:
    """Retourne is_confirmed + is_detected pour un lien adresse ↔ structure."""
    await cur.execute(
        """
        SELECT is_confirmed, (matched_form_id IS NOT NULL) AS is_detected
        FROM address_structures
        WHERE address_id = %s AND structure_id = %s
        """,
        (addr_id, structure_id),
    )
    return await cur.fetchone()


async def list_countries(cur: Any) -> list[dict[str, Any]]:
    """Liste des pays (code + nom)."""
    await cur.execute("SELECT code, name FROM countries ORDER BY (code = 'xx') DESC, name")
    return await cur.fetchall()


async def country_exists(cur: Any, code: str) -> bool:
    """Vérifie qu'un code pays existe."""
    await cur.execute("SELECT code FROM countries WHERE code = %s", (code,))
    return (await cur.fetchone()) is not None


async def address_exists(cur: Any, addr_id: int) -> bool:
    """Vérifie qu'une adresse existe."""
    await cur.execute("SELECT id FROM addresses WHERE id = %s", (addr_id,))
    return (await cur.fetchone()) is not None


@dataclass(frozen=True, slots=True)
class AddressCountriesFilters:
    search: str = ""
    has_country: str = ""  # "yes", "no", ""
    country_code: str = ""
    suggested_country: str = ""
    suggest: bool = False


async def addresses_countries(
    cur: Any, *, filters: AddressCountriesFilters, page: int, per_page: int
) -> dict[str, Any]:
    """Liste des adresses pour l'attribution de pays + facettes."""
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: list[Any] = []

    if filters.search:
        conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
        params.append(f"%{filters.search}%")
    if filters.has_country == "yes":
        conditions.append("a.countries IS NOT NULL")
    elif filters.has_country == "no":
        conditions.append("a.countries IS NULL")
    if filters.country_code:
        conditions.append("%s = ANY(a.countries)")
        params.append(filters.country_code)
    if filters.suggested_country:
        conditions.append("%s = ANY(a.suggested_countries)")
        params.append(filters.suggested_country)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    await cur.execute(f"SELECT COUNT(*) FROM addresses a {where}", params)
    total = (await cur.fetchone())["count"]

    await cur.execute(
        f"""
        SELECT a.id, a.raw_text, a.countries, a.suggested_countries, a.pub_count
        FROM addresses a
        {where}
        ORDER BY a.pub_count DESC, a.raw_text
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    addresses = [dict(r) for r in await cur.fetchall()]

    for a in addresses:
        sc = a.pop("suggested_countries", None)
        if filters.suggest and not a["countries"] and sc:
            a["suggested_countries"] = [{"code": c.strip(), "count": 1} for c in sc]
        else:
            a["suggested_countries"] = []

    result: dict[str, Any] = {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "addresses": addresses,
    }

    if filters.suggest and not filters.suggested_country:
        sug_where = where
        extra = "a.suggested_countries IS NOT NULL"
        sug_where = f"{sug_where} AND {extra}" if sug_where else f"WHERE {extra}"
        await cur.execute(
            f"""
            SELECT c AS code, COUNT(*) AS cnt
            FROM addresses a, unnest(a.suggested_countries) AS c
            {sug_where}
            GROUP BY c ORDER BY cnt DESC LIMIT 20
            """,
            params,
        )
        result["suggestion_facets"] = [
            {"code": r["code"].strip(), "count": r["cnt"]} for r in await cur.fetchall()
        ]

    # Facette pays (exclut country_code, garde le reste + a.countries IS NOT NULL)
    cf_conditions: list[str] = []
    cf_params: list[Any] = []
    if filters.search:
        cf_conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
        cf_params.append(f"%{filters.search}%")
    if filters.has_country == "yes":
        cf_conditions.append("a.countries IS NOT NULL")
    elif filters.has_country == "no":
        cf_conditions.append("a.countries IS NULL")
    if filters.suggested_country:
        cf_conditions.append("%s = ANY(a.suggested_countries)")
        cf_params.append(filters.suggested_country)
    cf_conditions.append("a.countries IS NOT NULL")
    cf_where = "WHERE " + " AND ".join(cf_conditions)
    await cur.execute(
        f"""
        SELECT c AS code, COUNT(*) AS cnt
        FROM addresses a, unnest(a.countries) AS c
        {cf_where}
        GROUP BY c ORDER BY cnt DESC
        """,
        cf_params,
    )
    result["country_facets"] = [
        {"code": r["code"].strip(), "count": r["cnt"]} for r in await cur.fetchall()
    ]

    return result


async def suggest_countries(cur: Any, search: str) -> dict[str, Any]:
    """Distribution des pays des adresses matchant un filtre + compte des sans-pays."""
    where_clause = ""
    params: list[Any] = []
    if search.strip():
        where_clause = "WHERE unaccent(a.raw_text) ILIKE unaccent(%s)"
        params = [f"%{search.strip()}%"]

    suggest_where = (
        where_clause.replace("WHERE", "WHERE a.countries IS NOT NULL AND")
        if where_clause
        else "WHERE a.countries IS NOT NULL"
    )
    await cur.execute(
        f"""
        SELECT c, COUNT(*) AS cnt
        FROM addresses a, unnest(a.countries) AS c
        {suggest_where}
        GROUP BY c ORDER BY cnt DESC
        """,
        params,
    )
    suggestions = [
        {"code": r["c"].strip(), "count": r["cnt"]} for r in await cur.fetchall()
    ]

    no_country_where = (
        where_clause.replace("WHERE", "WHERE countries IS NULL AND")
        if where_clause
        else "WHERE countries IS NULL"
    )
    await cur.execute(f"SELECT COUNT(*) FROM addresses a {no_country_where}", params)
    without_country = (await cur.fetchone())["count"]

    return {"suggestions": suggestions, "without_country": without_country}
