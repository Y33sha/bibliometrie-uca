"""Query services pour /api/publications/* (router publications).

Extrait du router pour respecter la séparation des couches (§1.1) : le
SQL vit dans infrastructure, le router devient mince.

Les dépendances externes (filtres réutilisables) viennent de
`infrastructure.db.queries.filters`.
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from infrastructure.db.queries.filters import (
    OA_OPEN_STATUSES,
    PUB_IS_UCA,
    apply_access_filter,
    apply_apc_filter,
    apply_corresponding_filter,
    apply_doc_type_filter,
    apply_hal_status_filter,
    apply_in_perimeter_person_filter,
    apply_lab_filter,
    apply_no_lab_filter,
    apply_oa_filter,
    apply_person_filter,
    apply_publisher_journal_filter,
    apply_source_filter,
    apply_year_filter,
)


@dataclass(frozen=True, slots=True)
class ListFilters:
    """Bundle des filtres pour list_publications / export_publications.
    Tous les champs ont un défaut — facilite les appels partiels."""

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""


def _build_list_conditions(
    cur: Any, filters: ListFilters, root_structure_id: int
) -> tuple[list[str], list[Any]]:
    """Construit les (conditions, params) communs à list et export.

    `cur` est utilisé pour charger la hal_collection du labo quand un
    filtre hal_status est actif (nécessite un seul lab_id).
    """
    if filters.person_id:
        conditions: list[str] = [
            """
            EXISTS (SELECT 1 FROM authorships a
                    JOIN source_authorships sa ON sa.authorship_id = a.id
                    WHERE a.publication_id = p.id AND a.person_id = %s
                      AND sa.roles && ARRAY['author']::text[])
        """
        ]
        params: list[Any] = [filters.person_id]
    elif filters.lab_none and not filters.lab_ids:
        conditions = [PUB_IS_UCA]
        params = []
    elif filters.lab_ids:
        conditions = []
        params = []
    else:
        conditions = [PUB_IS_UCA]
        params = []

    conditions.append("p.doc_type NOT IN ('peer_review', 'memoir')")
    if filters.excluded_types:
        conditions.append("p.doc_type::text != ALL(%s)")
        params.append(filters.excluded_types)
    if filters.search:
        conditions.append("unaccent(p.title) ILIKE unaccent(%s)")
        params.append(f"%{filters.search}%")
    if filters.years:
        conditions.append("p.pub_year = ANY(%s)")
        params.append(filters.years)
    if filters.doc_types:
        conditions.append("p.doc_type::text = ANY(%s)")
        params.append(filters.doc_types)

    if filters.lab_none and not filters.lab_ids:
        apply_no_lab_filter(conditions, params)
    elif filters.lab_ids:
        apply_lab_filter(conditions, params, filters.lab_ids)

    if filters.publisher_id:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM journals j2
                WHERE j2.id = p.journal_id AND j2.publisher_id = %s
            )
        """)
        params.append(filters.publisher_id)

    if filters.journal_id:
        conditions.append("p.journal_id = %s")
        params.append(filters.journal_id)

    if filters.source_values:
        apply_source_filter(conditions, filters.source_values)
    apply_access_filter(conditions, params, filters.access)
    apply_oa_filter(conditions, params, filters.oa_status)

    if filters.person_id:
        apply_corresponding_filter(conditions, params, filters.person_id, filters.is_corresponding)

    if filters.has_apc:
        apply_apc_filter(
            conditions, params, filters.has_apc, root_structure_id, lab_ids=filters.lab_ids
        )

    if filters.country_values:
        conditions.append("p.countries && %s::text[]")
        params.append(filters.country_values)

    if filters.hal_status_values and len(filters.lab_ids) == 1:
        cur.execute("SELECT hal_collection FROM structures WHERE id = %s", (filters.lab_ids[0],))
        lab_row = cur.fetchone()
        lab_hal_col = lab_row["hal_collection"] if lab_row else None
        apply_hal_status_filter(conditions, params, filters.hal_status_values, lab_hal_col)

    apply_in_perimeter_person_filter(conditions, params, filters.in_perimeter, filters.person_id)
    return conditions, params


_APC_SORT = (
    "(SELECT COALESCE(SUM(ap.amount_eur_ht), 0) FROM apc_payments ap "
    "WHERE ap.publication_id = p.id)"
)

_ORDER_MAP = {
    "year_desc": "p.pub_year DESC, p.title",
    "year_asc": "p.pub_year ASC, p.title",
    "title": "p.title ASC",
    "title_desc": "p.title DESC",
    "apc_desc": f"{_APC_SORT} DESC, p.title",
    "apc_asc": f"{_APC_SORT} ASC, p.title",
    "soutenance_desc": "p.meta->>'date_soutenance' DESC NULLS LAST, p.title",
    "soutenance_asc": "p.meta->>'date_soutenance' ASC NULLS LAST, p.title",
    "inscription_desc": "p.meta->>'date_inscription' DESC NULLS LAST, p.title",
    "inscription_asc": "p.meta->>'date_inscription' ASC NULLS LAST, p.title",
}


# ── Liste paginée ─────────────────────────────────────────────────


def list_publications(
    cur: Any,
    *,
    filters: ListFilters,
    root_structure_id: int,
    page: int,
    per_page: int,
    sort: str,
) -> dict[str, Any]:
    """Liste paginée des publications avec sources, labos, journal."""
    cur.execute("SET LOCAL jit = off")
    offset = (page - 1) * per_page
    conditions, params = _build_list_conditions(cur, filters, root_structure_id)
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    order = _ORDER_MAP.get(sort, "p.pub_year DESC, p.title")

    cur.execute(f"SELECT COUNT(*) FROM publications p WHERE {where_clause}", params)
    total = cur.fetchone()["count"]

    cur.execute(
        f"""
        SELECT
            p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
            p.oa_status::text,
            j.title AS journal_title,
            pub.name AS publisher_name,
            src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
            src_ids.wos_id, src_ids.theses_id, src_ids.hal_collections,
            p.meta->>'date_soutenance' AS date_soutenance,
            p.meta->>'date_inscription' AS date_inscription,
            (SELECT a.is_corresponding FROM authorships a
             WHERE a.publication_id = p.id AND a.person_id = %s
               AND NOT a.excluded
             LIMIT 1) AS is_corresponding,
            (SELECT a.id FROM authorships a
             WHERE a.publication_id = p.id AND a.person_id = %s
               AND NOT a.excluded
             LIMIT 1) AS authorship_id,
            (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                     ORDER BY COALESCE(s.acronym, s.name))
             FROM authorships a3
             CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
             JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
             WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
               AND a3.structure_ids IS NOT NULL
            ) AS labs,
            (SELECT json_agg(sub ORDER BY sub.label)
             FROM (
                SELECT DISTINCT s.id, COALESCE(s.acronym, s.name) AS label
                FROM authorships a4
                CROSS JOIN LATERAL unnest(a4.structure_ids) AS struct_id
                JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
                WHERE a4.publication_id = p.id AND a4.in_perimeter = TRUE
                  AND a4.structure_ids IS NOT NULL
             ) sub
            ) AS lab_items,
            (SELECT json_agg(json_build_object(
                'amount', ap.amount_eur_ht,
                'institution', ap.institution,
                'lab_id', ap.lab_structure_id,
                'lab_acronym', ls.acronym,
                'budget_structure_id', ap.budget_structure_id
             ))
             FROM apc_payments ap
             LEFT JOIN structures ls ON ls.id = ap.lab_structure_id
             WHERE ap.publication_id = p.id
            ) AS apc_details
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        LEFT JOIN LATERAL (
            SELECT
                max(CASE WHEN sd.source = 'hal' THEN sd.source_id END) AS hal_id,
                max(CASE WHEN sd.source = 'openalex' THEN sd.source_id END) AS openalex_id,
                max(CASE WHEN sd.source = 'scanr' THEN sd.source_id END) AS scanr_id,
                max(CASE WHEN sd.source = 'wos' THEN sd.source_id END) AS wos_id,
                max(CASE WHEN sd.source = 'theses' THEN sd.source_id END) AS theses_id,
                (SELECT sd2.hal_collections FROM source_publications sd2
                 WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
                 LIMIT 1) AS hal_collections
            FROM source_publications sd WHERE sd.publication_id = p.id
        ) src_ids ON TRUE
        WHERE {where_clause}
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        [filters.person_id, filters.person_id] + params + [per_page, offset],
    )

    publications = [
        {
            "id": r["id"],
            "title": r["title"],
            "pub_year": r["pub_year"],
            "doi": r["doi"],
            "doc_type": r["doc_type"],
            "oa_status": r["oa_status"],
            "journal": r["journal_title"],
            "publisher": r["publisher_name"],
            "hal_id": r["hal_id"],
            "openalex_id": r["openalex_id"],
            "scanr_id": r["scanr_id"],
            "wos_id": r["wos_id"],
            "theses_id": r["theses_id"],
            "date_soutenance": r["date_soutenance"],
            "date_inscription": r["date_inscription"],
            "labs": r["labs"],
            "lab_items": r["lab_items"],
            "apc": r["apc_details"],
            "is_corresponding": r["is_corresponding"],
            "authorship_id": r["authorship_id"],
            "hal_collections": r["hal_collections"],
        }
        for r in cur.fetchall()
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "publications": publications,
    }


# ── Export CSV ────────────────────────────────────────────────────


def export_publications_csv(  # noqa: C901 (reproduction fidèle du comportement historique)
    cur: Any, *, filters: ListFilters, root_structure_id: int, sort: str
) -> str:
    """Export CSV (sans pagination) avec les mêmes filtres que list_publications.

    Retourne la string CSV (préfixée d'un BOM UTF-8 pour Excel). Le caller
    (router) est responsable d'emballer la réponse HTTP.

    Simplification : les filtres hal_status / in_perimeter ne sont pas
    appliqués dans l'export historique, on reproduit ce comportement.
    """
    cur.execute("SET LOCAL jit = off")
    # L'export utilise un sous-ensemble simplifié des filtres — on reproduit
    # la construction historique manuelle pour préserver le comportement.
    if filters.person_id:
        conditions: list[str] = [
            """
            EXISTS (SELECT 1 FROM source_publications sd
                    JOIN source_authorships sa ON sa.source_publication_id = sd.id
                    WHERE sd.publication_id = p.id AND sa.person_id = %s
                      AND sa.excluded = FALSE
                      AND sa.roles && ARRAY['author']::text[])
        """
        ]
        params: list[Any] = [filters.person_id]
    elif filters.lab_none and not filters.lab_ids:
        conditions = [PUB_IS_UCA]
        params = []
    elif filters.lab_ids:
        conditions = []
        params = []
    else:
        conditions = [PUB_IS_UCA]
        params = []

    conditions.append("p.doc_type NOT IN ('peer_review', 'memoir')")
    if filters.excluded_types:
        conditions.append("p.doc_type::text != ALL(%s)")
        params.append(filters.excluded_types)
    if filters.search:
        conditions.append("unaccent(p.title) ILIKE unaccent(%s)")
        params.append(f"%{filters.search}%")
    if filters.years:
        conditions.append("p.pub_year = ANY(%s)")
        params.append(filters.years)
    if filters.doc_types:
        conditions.append("p.doc_type::text = ANY(%s)")
        params.append(filters.doc_types)
    if filters.lab_none and not filters.lab_ids:
        apply_no_lab_filter(conditions, params)
    elif filters.lab_ids:
        apply_lab_filter(conditions, params, filters.lab_ids)
    if filters.publisher_id:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM journals j2
                WHERE j2.id = p.journal_id AND j2.publisher_id = %s
            )
        """)
        params.append(filters.publisher_id)
    if filters.journal_id:
        conditions.append("p.journal_id = %s")
        params.append(filters.journal_id)
    if filters.source_values:
        for sv in filters.source_values:
            if sv == "hal_yes":
                conditions.append("p.sources @> ARRAY['hal'::source_type]")
            elif sv == "hal_no":
                conditions.append("NOT p.sources @> ARRAY['hal'::source_type]")
            elif sv == "oa_yes":
                conditions.append("p.sources @> ARRAY['openalex'::source_type]")
            elif sv == "oa_no":
                conditions.append("NOT p.sources @> ARRAY['openalex'::source_type]")
    if filters.oa_status:
        oa_values = [v.strip() for v in filters.oa_status.split(",") if v.strip()]
        if oa_values:
            expanded: list[str] = []
            for v in oa_values:
                if v == "oa":
                    expanded.extend(OA_OPEN_STATUSES)
                else:
                    expanded.append(v)
            conditions.append("p.oa_status::text = ANY(%s)")
            params.append(list(set(expanded)))

    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    order = _ORDER_MAP.get(sort, "p.pub_year DESC, p.title")

    cur.execute(
        f"""
        SELECT
            p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
            p.oa_status::text,
            j.title AS journal_title,
            pub.name AS publisher_name,
            src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
            src_ids.wos_id, src_ids.theses_id,
            (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                     ORDER BY COALESCE(s.acronym, s.name))
             FROM authorships a3
             CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
             JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
             WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
               AND a3.structure_ids IS NOT NULL
            ) AS labs
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        LEFT JOIN LATERAL (
            SELECT
                max(CASE WHEN sd.source = 'hal' THEN sd.source_id END) AS hal_id,
                max(CASE WHEN sd.source = 'openalex' THEN sd.source_id END) AS openalex_id,
                max(CASE WHEN sd.source = 'scanr' THEN sd.source_id END) AS scanr_id,
                max(CASE WHEN sd.source = 'wos' THEN sd.source_id END) AS wos_id,
                max(CASE WHEN sd.source = 'theses' THEN sd.source_id END) AS theses_id
            FROM source_publications sd WHERE sd.publication_id = p.id
        ) src_ids ON TRUE
        WHERE {where_clause}
        ORDER BY {order}
        """,
        params,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Année",
            "Titre",
            "DOI",
            "Revue",
            "Éditeur",
            "Laboratoires",
            "Type",
            "Voie OA",
            "HAL",
            "OpenAlex",
            "WoS",
        ]
    )
    for row in cur.fetchall():
        hal_url = f"https://hal.science/{row['hal_id']}" if row["hal_id"] else ""
        oa_url = f"https://openalex.org/{row['openalex_id']}" if row["openalex_id"] else ""
        wos_url = (
            f"https://www.webofscience.com/wos/woscc/full-record/{row['wos_id']}"
            if row["wos_id"]
            else ""
        )
        writer.writerow(
            [
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
                wos_url,
            ]
        )

    return "\ufeff" + buf.getvalue()


# ── Facettes ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FacetFilters:
    """Bundle spécifique aux facettes (similaire à ListFilters mais sans
    pagination/sort et avec variables mutables pour lab_hal_col)."""

    years: list[int] = field(default_factory=list)
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""


def publications_facets(  # noqa: C901 (15 facettes, à décomposer plus tard)
    cur: Any, *, filters: FacetFilters, root_structure_id: int
) -> dict[str, Any]:
    """Facettes dynamiques : chaque facette exclut son propre filtre mais
    applique tous les autres."""
    cur.execute("SET LOCAL jit = off")

    def base_conds_params() -> tuple[list[str], list[Any]]:
        if filters.person_id:
            c: list[str] = ["p.doc_type NOT IN ('peer_review', 'memoir')"]
            p: list[Any] = []
            apply_person_filter(c, p, filters.person_id)
        else:
            c, p = [PUB_IS_UCA], []
        if filters.excluded_types:
            c.append("p.doc_type::text != ALL(%s)")
            p.append(filters.excluded_types)
        return c, p

    lab_hal_col: list[Any] = [None]

    def add_all_except(conds: list[str], params: list[Any], *, skip: str) -> None:
        if skip != "year":
            apply_year_filter(conds, params, filters.years)
        if skip != "corresponding" and filters.person_id:
            apply_corresponding_filter(conds, params, filters.person_id, filters.is_corresponding)
        if skip != "lab":
            if filters.lab_none and not filters.lab_ids:
                apply_no_lab_filter(conds, params)
            elif filters.lab_ids:
                apply_lab_filter(conds, params, filters.lab_ids)
        if skip != "doc_type":
            apply_doc_type_filter(conds, params, filters.doc_types)
        if skip != "access":
            apply_access_filter(conds, params, filters.access)
        if skip != "oa_status":
            apply_oa_filter(conds, params, filters.oa_status)
        if skip != "source":
            apply_source_filter(conds, filters.source_values)
        if skip != "apc":
            apply_apc_filter(
                conds, params, filters.has_apc, root_structure_id, lab_ids=filters.lab_ids
            )
        apply_publisher_journal_filter(conds, params, filters.publisher_id, filters.journal_id)
        if skip != "country" and filters.country_values:
            conds.append("p.countries && %s::text[]")
            params.append(filters.country_values)
        if skip != "hal_status":
            apply_hal_status_filter(conds, params, filters.hal_status_values, lab_hal_col[0])
        if skip != "in_perimeter":
            apply_in_perimeter_person_filter(conds, params, filters.in_perimeter, filters.person_id)

    def where_sql(conds: list[str]) -> str:
        return " AND ".join(conds) if conds else "TRUE"

    # Pré-charger la hal_collection du labo (utilisée par hal_status filter)
    if len(filters.lab_ids) == 1:
        cur.execute("SELECT hal_collection FROM structures WHERE id = %s", (filters.lab_ids[0],))
        row = cur.fetchone()
        lab_hal_col[0] = row["hal_collection"] if row else None

    # --- ANNÉES ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="year")
    cur.execute(
        f"""
        SELECT p.pub_year AS value, COUNT(*) AS count
        FROM publications p
        WHERE {where_sql(c)} AND p.pub_year IS NOT NULL
        GROUP BY p.pub_year ORDER BY p.pub_year DESC
        """,
        p,
    )
    year_facets = cur.fetchall()

    # --- LABOS ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="lab")
    cur.execute(
        f"""
        SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT a.publication_id) AS count
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
        JOIN structures s ON s.id = struct_id
        WHERE {where_sql(c)}
          AND s.structure_type = 'labo'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY count DESC
        """,
        p,
    )
    lab_facets = cur.fetchall()

    cur.execute(
        f"""
        SELECT COUNT(*) AS count FROM publications p
        WHERE {where_sql(c)}
          AND NOT EXISTS (
              SELECT 1 FROM authorships a
              JOIN structures s ON s.id = ANY(a.structure_ids)
              WHERE a.publication_id = p.id
                AND NOT a.excluded
                AND s.structure_type = 'labo'
          )
        """,
        p,
    )
    no_lab_count = cur.fetchone()["count"]

    # --- DOC_TYPE ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="doc_type")
    cur.execute(
        f"""
        SELECT p.doc_type::text AS value, COUNT(*) AS count
        FROM publications p
        WHERE {where_sql(c)} AND p.doc_type IS NOT NULL
        GROUP BY p.doc_type ORDER BY count DESC
        """,
        p,
    )
    doc_type_facets = cur.fetchall()

    # --- ACCÈS ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="access")
    cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE p.oa_status::text IN ('gold','hybrid','bronze','green','diamond')) AS open_count,
            COUNT(*) FILTER (WHERE p.oa_status::text IN ('closed','unknown') OR p.oa_status IS NULL) AS closed_count
        FROM publications p
        WHERE {where_sql(c)}
        """,
        p,
    )
    access_row = cur.fetchone()
    access_facets = [
        {"value": "open", "text": "Ouvert", "count": access_row["open_count"]},
        {"value": "closed", "text": "Fermé", "count": access_row["closed_count"]},
    ]

    # --- OA_STATUS ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="oa_status")
    cur.execute(
        f"""
        SELECT p.oa_status::text AS value, COUNT(*) AS count
        FROM publications p
        WHERE {where_sql(c)} AND p.oa_status IS NOT NULL
        GROUP BY p.oa_status ORDER BY count DESC
        """,
        p,
    )
    oa_facets = cur.fetchall()

    # --- CORRESPONDING ---
    corr_facets: list[dict[str, Any]] = []
    if filters.person_id:
        c, p = base_conds_params()
        add_all_except(c, p, skip="corresponding")
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM authorships a
                    WHERE a.publication_id = p.id AND a.person_id = %s
                      AND a.is_corresponding = TRUE AND NOT a.excluded
                )) AS yes_count,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM authorships a
                    WHERE a.publication_id = p.id AND a.person_id = %s
                      AND a.is_corresponding = TRUE AND NOT a.excluded
                )) AS no_count
            FROM publications p
            WHERE {where_sql(c)}
            """,
            [filters.person_id, filters.person_id] + p,
        )
        row = cur.fetchone()
        corr_facets = [
            {"value": "yes", "count": row["yes_count"]},
            {"value": "no", "count": row["no_count"]},
        ]

    # --- SOURCES ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="source")
    cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE p.sources @> ARRAY['hal'::source_type]) AS hal_count,
            COUNT(*) FILTER (WHERE p.sources @> ARRAY['openalex'::source_type]) AS oa_count,
            COUNT(*) FILTER (WHERE p.sources @> ARRAY['scanr'::source_type]) AS scanr_count,
            COUNT(*) FILTER (WHERE p.sources @> ARRAY['wos'::source_type]) AS wos_count,
            COUNT(*) FILTER (WHERE p.sources @> ARRAY['theses'::source_type]) AS theses_count
        FROM publications p
        WHERE {where_sql(c)}
        """,
        p,
    )
    source_counts = cur.fetchone()

    # --- APC ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="apc")
    where = where_sql(c)
    if filters.lab_ids:
        apc_sql = f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])
                )) AS apc_this_lab,
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
                ) AND NOT EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])
                )) AS apc_other_uca,
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
                )) AS apc_non_uca,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                )) AS apc_none
            FROM publications p
            WHERE {where}
        """
        cur.execute(
            apc_sql, [filters.lab_ids, root_structure_id, filters.lab_ids, root_structure_id] + p
        )
        r = cur.fetchone()
        cur.execute(
            "SELECT COALESCE(acronym, name) AS label FROM structures WHERE id = %s",
            (filters.lab_ids[0],),
        )
        lab_label = cur.fetchone()["label"] if cur.rowcount else "ce labo"
        apc_facets = [
            {"value": "this_lab", "text": f"APC — {lab_label}", "count": r["apc_this_lab"]},
            {"value": "other_uca", "text": "APC — autres UCA", "count": r["apc_other_uca"]},
            {"value": "non_uca", "text": "APC hors UCA", "count": r["apc_non_uca"]},
            {"value": "none", "text": "Sans APC", "count": r["apc_none"]},
        ]
    else:
        apc_sql = f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
                )) AS apc_uca,
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
                )) AS apc_other,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                )) AS apc_none
            FROM publications p
            WHERE {where}
        """
        cur.execute(apc_sql, [root_structure_id, root_structure_id] + p)
        r = cur.fetchone()
        apc_facets = [
            {"value": "uca", "text": "APC — UCA", "count": r["apc_uca"]},
            {"value": "other", "text": "APC — autres", "count": r["apc_other"]},
            {"value": "none", "text": "Sans APC", "count": r["apc_none"]},
        ]

    # --- COUNTRIES ---
    c, p = base_conds_params()
    add_all_except(c, p, skip="country")
    cur.execute(
        f"""
        SELECT co.code, co.name, COUNT(*) AS count
        FROM (
            SELECT unnest(p.countries) AS cc
            FROM publications p
            WHERE {where_sql(c)} AND p.countries IS NOT NULL
        ) sub
        JOIN countries co ON co.code = sub.cc
        GROUP BY co.code, co.name
        ORDER BY count DESC
        """,
        p,
    )
    country_facets = [
        {"value": r["code"].strip(), "text": r["name"], "count": r["count"]}
        for r in cur.fetchall()
        if r["code"].strip() != "xx"
    ]

    # --- HAL STATUS (seulement avec un seul labo) ---
    hal_status_facets: list[dict[str, Any]] = []
    if len(filters.lab_ids) == 1:
        cur.execute("SELECT hal_collection FROM structures WHERE id = %s", (filters.lab_ids[0],))
        lab_row = cur.fetchone()
        col = lab_row["hal_collection"] if lab_row else None

        c, p = base_conds_params()
        add_all_except(c, p, skip="hal_status")

        if col:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                    )) AS hors_hal,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                          AND (sd.hal_collections IS NULL OR NOT sd.hal_collections @> ARRAY[%s])
                    )) AS hors_collection,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                          AND sd.hal_collections @> ARRAY[%s]
                    ) AND (p.oa_status IS NULL OR p.oa_status::text IN ('closed', 'unknown'))
                    ) AS notice,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                          AND sd.hal_collections @> ARRAY[%s]
                    ) AND p.oa_status IS NOT NULL
                      AND p.oa_status::text NOT IN ('closed', 'unknown')
                    ) AS ok
                FROM publications p
                WHERE {where_sql(c)}
                """,
                [col, col, col] + p,
            )
        else:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                    )) AS hors_hal,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                    )) AS hors_collection,
                    0 AS notice,
                    0 AS ok
                FROM publications p
                WHERE {where_sql(c)}
                """,
                p,
            )
        r = cur.fetchone()
        hal_status_facets = [
            {"value": "ok", "text": "OK", "count": r["ok"]},
            {"value": "notice", "text": "Notice", "count": r["notice"]},
            {"value": "hors_collection", "text": "Hors collection", "count": r["hors_collection"]},
            {"value": "hors_hal", "text": "Hors HAL", "count": r["hors_hal"]},
        ]

    # --- IN_PERIMETER ---
    perimeter_facets: list[dict[str, Any]] = []
    if filters.person_id:
        c, p = base_conds_params()
        add_all_except(c, p, skip="in_perimeter")
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM authorships a
                    WHERE a.publication_id = p.id AND a.person_id = %s
                      AND a.in_perimeter = TRUE AND NOT a.excluded
                )) AS yes,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM authorships a
                    WHERE a.publication_id = p.id AND a.person_id = %s
                      AND a.in_perimeter = TRUE AND NOT a.excluded
                )) AS no
            FROM publications p
            WHERE {where_sql(c)}
            """,
            [filters.person_id, filters.person_id] + p,
        )
        r = cur.fetchone()
        perimeter_facets = [
            {"value": "yes", "text": "UCA", "count": r["yes"]},
            {"value": "no", "text": "Hors périmètre", "count": r["no"]},
        ]

    return {
        "years": year_facets,
        "labs": lab_facets,
        "no_lab_count": no_lab_count,
        "doc_types": doc_type_facets,
        "access": access_facets,
        "oa_statuses": oa_facets,
        "corresponding": corr_facets,
        "source_counts": {
            "hal": source_counts["hal_count"],
            "oa": source_counts["oa_count"],
            "scanr": source_counts["scanr_count"],
            "wos": source_counts["wos_count"],
            "theses": source_counts["theses_count"],
        },
        "apc": apc_facets,
        "countries": country_facets,
        "hal_status": hal_status_facets,
        "in_perimeter": perimeter_facets,
    }


# ── Années ────────────────────────────────────────────────────────


def all_years(cur: Any) -> list[int]:
    """Toutes les années de publication disponibles (hors filtre UCA)."""
    cur.execute("""
        SELECT DISTINCT pub_year FROM publications
        WHERE pub_year IS NOT NULL
        ORDER BY pub_year DESC
    """)
    return [r["pub_year"] for r in cur.fetchall()]


# ── Détail ────────────────────────────────────────────────────────


def get_publication_detail(cur: Any, pub_id: int) -> dict[str, Any] | None:
    """Détail complet d'une publication : métadonnées, sources, authorships.

    Retourne None si la publication n'existe pas (caller = 404).
    """
    cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doi, p.doc_type::text, p.oa_status::text,
               p.language, p.container_title, p.abstract,
               j.id AS journal_id, j.title AS journal_title, j.issn, j.eissn,
               j.is_predatory AS journal_predatory, j.apc_amount, j.apc_currency,
               j.oa_model,
               pub.id AS publisher_id, pub.name AS publisher_name,
               pub.is_predatory AS publisher_predatory
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        WHERE p.id = %s
        """,
        (pub_id,),
    )
    pub = cur.fetchone()
    if not pub:
        return None

    cur.execute(
        """
        SELECT sd.source, sd.source_id, sd.doi, sd.hal_collections, sd.countries
        FROM source_publications sd WHERE sd.publication_id = %s
        """,
        (pub_id,),
    )
    sources = cur.fetchall()

    cur.execute(
        """
        SELECT a.author_position, a.in_perimeter, a.is_corresponding,
               a.structure_ids,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'hal') AS source_hal,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'openalex') AS source_openalex,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'wos') AS source_wos,
               pe.id AS person_id, pe.last_name, pe.first_name
        FROM authorships a
        JOIN persons pe ON pe.id = a.person_id
        WHERE a.publication_id = %s AND NOT a.excluded
        ORDER BY a.author_position
        """,
        (pub_id,),
    )
    authorships = cur.fetchall()

    cur.execute(
        """
        SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
               sa.in_perimeter, sa.structure_ids, sa.excluded, sa.countries
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.source = 'hal' AND sd.publication_id = %s
        ORDER BY sa.author_position
        """,
        (pub_id,),
    )
    hal_authorships = cur.fetchall()

    cur.execute(
        """
        SELECT sa.id, sa.author_position,
               sa.raw_author_name AS full_name,
               sa.person_id,
               sa.in_perimeter, sa.structure_ids,
               (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id) FROM source_authorship_addresses saa2 JOIN addresses addr ON addr.id = saa2.address_id WHERE saa2.source_authorship_id = sa.id) AS raw_affiliation,
               sa.excluded,
               COALESCE(sa.countries,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorship_addresses saa
                    JOIN addresses addr ON addr.id = saa.address_id,
                         unnest(addr.countries) AS c
                    WHERE saa.source_authorship_id = sa.id
                      AND addr.countries IS NOT NULL)
               ) AS countries
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.source = 'openalex' AND sd.publication_id = %s
        ORDER BY sa.author_position
        """,
        (pub_id,),
    )
    oa_authorships = cur.fetchall()

    cur.execute(
        """
        SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
               sa.in_perimeter, sa.structure_ids,
               (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id) FROM source_authorship_addresses saa2 JOIN addresses addr ON addr.id = saa2.address_id WHERE saa2.source_authorship_id = sa.id) AS raw_affiliation,
               sa.excluded,
               COALESCE(sa.countries,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorship_addresses saa
                    JOIN addresses addr ON addr.id = saa.address_id,
                         unnest(addr.countries) AS c
                    WHERE saa.source_authorship_id = sa.id
                      AND addr.countries IS NOT NULL)
               ) AS countries
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.source = 'wos' AND sd.publication_id = %s
        ORDER BY sa.author_position
        """,
        (pub_id,),
    )
    wos_authorships = cur.fetchall()

    cur.execute(
        """
        SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
               sa.roles, sa.in_perimeter
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.source = 'theses' AND sd.publication_id = %s
        ORDER BY sa.author_position NULLS LAST, sa.raw_author_name
        """,
        (pub_id,),
    )
    theses_authorships = cur.fetchall()

    thesis_meta = None
    if pub["doc_type"] in ("thesis", "ongoing_thesis"):
        cur.execute(
            """
            SELECT sd.meta AS sd_meta, p.meta AS pub_meta
            FROM publications p
            LEFT JOIN source_publications sd ON sd.publication_id = p.id AND sd.source = 'theses'
            WHERE p.id = %s
            LIMIT 1
            """,
            (pub_id,),
        )
        row = cur.fetchone()
        if row:
            sd_meta = row["sd_meta"] or {}
            pub_meta = row["pub_meta"] or {}
            thesis_meta = {
                "discipline": sd_meta.get("discipline"),
                "ecoles_doctorales": sd_meta.get("ecoles_doctorales"),
                "partenaires": sd_meta.get("partenaires"),
                "date_soutenance": sd_meta.get("date_soutenance")
                or pub_meta.get("date_soutenance"),
                "date_inscription": sd_meta.get("date_inscription")
                or pub_meta.get("date_inscription"),
            }

    all_struct_ids: set[int] = set()
    for row in authorships:
        if row["structure_ids"]:
            all_struct_ids.update(row["structure_ids"])
    for row in hal_authorships:
        if row["structure_ids"]:
            all_struct_ids.update(row["structure_ids"])
    for row in oa_authorships:
        if row["structure_ids"]:
            all_struct_ids.update(row["structure_ids"])
    for row in wos_authorships:
        if row["structure_ids"]:
            all_struct_ids.update(row["structure_ids"])

    structures: dict[str, Any] = {}
    if all_struct_ids:
        cur.execute(
            """
            SELECT id, acronym, name, structure_type AS type FROM structures
            WHERE id = ANY(%s)
            """,
            (list(all_struct_ids),),
        )
        for s in cur.fetchall():
            structures[str(s["id"])] = {
                "acronym": s["acronym"],
                "name": s["name"],
                "type": s["type"],
            }

    return {
        "publication": dict(pub),
        "sources": [dict(s) for s in sources],
        "authorships": [dict(a) for a in authorships],
        "hal_authorships": [dict(a) for a in hal_authorships],
        "openalex_authorships": [dict(a) for a in oa_authorships],
        "wos_authorships": [dict(a) for a in wos_authorships],
        "theses_authorships": [dict(a) for a in theses_authorships],
        "thesis_meta": thesis_meta,
        "structures": structures,
    }
