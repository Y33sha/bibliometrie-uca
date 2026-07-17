"""Années disponibles et facettes croisées des statistiques."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, Row, text

from infrastructure.queries.api.stats._shared import stats_apc_clause
from infrastructure.queries.filters import (
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    assemble_where,
    doc_type_clause,
    lab_clause,
    oa_clause,
    year_clause,
)

# Périmètre : corpus in-perimeter, hors revues-dépôts. Le type de document n'est PAS figé ici —
# c'est un filtre comme un autre (facette « Type de document »), porté par `doc_type_clause`.
_BASE_CLAUSES = " AND ".join(
    [
        PUBLICATION_IS_IN_PERIMETER,
        "(j.oa_model IS DISTINCT FROM 'repository')",
    ]
)


def _publisher_journal_clauses(
    publisher_ids: list[int], journal_ids: list[int]
) -> list[WhereClause | None]:
    out: list[WhereClause | None] = []
    if publisher_ids:
        out.append(
            WhereClause(
                "j.publisher_id = ANY(:flt_publisher_ids)", {"flt_publisher_ids": publisher_ids}
            )
        )
    if journal_ids:
        out.append(
            WhereClause("p.journal_id = ANY(:flt_journal_ids)", {"flt_journal_ids": journal_ids})
        )
    return out


def _common_clauses(
    *,
    perimeter_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_ids: list[int],
    journal_ids: list[int],
    oa_status: list[str],
    has_apc: list[str],
    doc_types: list[str],
    skip: str = "",
) -> list[WhereClause | None]:
    """Construit les filtres communs aux facettes croisées.

    `skip` permet d'omettre un filtre pour les facettes croisées ("year",
    "lab", "oa", "apc", "doc_type"). Les filtres éditeur/revue sont toujours
    appliqués (jamais facettés via cette barre — ils passent par la recherche serveur).
    """
    out: list[WhereClause | None] = []
    if skip != "year":
        out.append(year_clause(years))
    if skip != "lab":
        out.append(lab_clause(lab_ids))
    out.extend(_publisher_journal_clauses(publisher_ids, journal_ids))
    if skip != "oa":
        out.append(oa_clause(oa_status))
    if skip != "apc":
        out.append(stats_apc_clause(has_apc, perimeter_structure_ids))
    if skip != "doc_type":
        out.append(doc_type_clause(doc_types))
    return out


_AVAILABLE_YEARS_SQL = f"""
    SELECT DISTINCT pub_year FROM publications p
    WHERE {PUBLICATION_IS_IN_PERIMETER} AND pub_year IS NOT NULL
    ORDER BY pub_year DESC
"""


def available_years(conn: Connection) -> list[int]:
    """Liste des années de publication disponibles."""
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(text(_AVAILABLE_YEARS_SQL)).all()
    return [r.pub_year for r in rows]


def _facets_sqls(
    *,
    perimeter_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_ids: list[int],
    journal_ids: list[int],
    oa_status: list[str],
    has_apc: list[str],
    doc_types: list[str],
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Retourne {facet_name: (sql, binds)} pour les 4 sous-requêtes facettes."""

    def _clauses(skip: str) -> list[WhereClause | None]:
        return _common_clauses(
            perimeter_structure_ids=perimeter_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_ids=publisher_ids,
            journal_ids=journal_ids,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
            skip=skip,
        )

    year_where, year_binds = assemble_where(_clauses("year"))
    year_sql = f"""
        SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {_BASE_CLAUSES} AND {year_where}
          AND p.pub_year IS NOT NULL
        GROUP BY p.pub_year
        ORDER BY p.pub_year DESC
    """

    lab_where, lab_binds = assemble_where(_clauses("lab"))
    lab_sql = f"""
        SELECT s.id, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT a.publication_id) AS count
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        LEFT JOIN journals j ON j.id = p.journal_id
        JOIN authorship_structures aus ON aus.authorship_id = a.id
        JOIN structures s ON s.id = aus.structure_id
        WHERE {_BASE_CLAUSES} AND {lab_where}
          AND s.structure_type = 'labo'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY count DESC
    """

    oa_where, oa_binds = assemble_where(_clauses("oa"))
    oa_sql = f"""
        SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {_BASE_CLAUSES} AND {oa_where}
          AND p.oa_status IS NOT NULL
        GROUP BY p.oa_status
        ORDER BY count DESC
    """

    apc_where, apc_binds = assemble_where(_clauses("apc"))
    apc_sql = f"""
        SELECT
            COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                SELECT 1 FROM apc_payments ap
                WHERE ap.publication_id = p.id
                  AND ap.budget_structure_id = ANY(CAST(:apc_root_ids AS int[]))
            )) AS apc_uca,
            COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
            ) AND NOT EXISTS (
                SELECT 1 FROM apc_payments ap
                WHERE ap.publication_id = p.id
                  AND ap.budget_structure_id = ANY(CAST(:apc_root_ids AS int[]))
            )) AS apc_non_uca,
            COUNT(DISTINCT p.id) FILTER (WHERE NOT EXISTS (
                SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
            )) AS apc_none
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {_BASE_CLAUSES} AND {apc_where}
    """

    dt_where, dt_binds = assemble_where(_clauses("doc_type"))
    doc_type_sql = f"""
        SELECT p.doc_type::text AS value, COUNT(DISTINCT p.id) AS count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {_BASE_CLAUSES} AND {dt_where}
        GROUP BY p.doc_type
        ORDER BY count DESC
    """

    return {
        "year": (year_sql, year_binds),
        "lab": (lab_sql, lab_binds),
        "oa": (oa_sql, oa_binds),
        "apc": (apc_sql, {**apc_binds, "apc_root_ids": perimeter_structure_ids}),
        "doc_type": (doc_type_sql, dt_binds),
    }


def stats_facets(
    conn: Connection,
    *,
    perimeter_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_ids: list[int],
    journal_ids: list[int],
    oa_status: list[str],
    has_apc: list[str],
    doc_types: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Facettes dynamiques."""
    conn.execute(text("SET LOCAL jit = off"))
    sqls = _facets_sqls(
        perimeter_structure_ids=perimeter_structure_ids,
        lab_ids=lab_ids,
        years=years,
        publisher_ids=publisher_ids,
        journal_ids=journal_ids,
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=doc_types,
    )

    year_rows = conn.execute(text(sqls["year"][0]), sqls["year"][1]).all()
    lab_rows = conn.execute(text(sqls["lab"][0]), sqls["lab"][1]).all()
    oa_rows = conn.execute(text(sqls["oa"][0]), sqls["oa"][1]).all()
    apc_row = conn.execute(text(sqls["apc"][0]), sqls["apc"][1]).one()
    doc_type_rows = conn.execute(text(sqls["doc_type"][0]), sqls["doc_type"][1]).all()

    return _build_facets_result(year_rows, lab_rows, oa_rows, apc_row, doc_type_rows)


def _build_facets_result(
    year_rows: Sequence[Row[Any]],
    lab_rows: Sequence[Row[Any]],
    oa_rows: Sequence[Row[Any]],
    apc_row: Row[Any],
    doc_type_rows: Sequence[Row[Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "years": [{"value": r.pub_year, "count": r.count} for r in year_rows],
        "labs": [{"value": r.id, "label": r.label, "count": r.count} for r in lab_rows],
        "oa_statuses": [{"value": r.value, "count": r.count} for r in oa_rows],
        "doc_types": [{"value": r.value, "count": r.count} for r in doc_type_rows],
        "apc": [
            {"value": "uca", "text": "APC UCA", "count": apc_row.apc_uca},
            {"value": "non_uca", "text": "APC hors UCA", "count": apc_row.apc_non_uca},
            {"value": "none", "text": "Sans APC", "count": apc_row.apc_none},
        ],
    }
