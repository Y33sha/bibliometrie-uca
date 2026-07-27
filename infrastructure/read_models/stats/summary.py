"""Années disponibles et facettes croisées des statistiques."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, Row, text

from application.ports.read_models._common import FacetOption
from application.ports.read_models.stats_queries import StatsFacetsResponse, StatsFilters
from domain.structures.structure import StructureType
from infrastructure.read_models.filters import WhereClause, assemble_where
from infrastructure.read_models.stats._shared import STATS_BASE, stats_filter_clauses


def _facets_sqls(
    *,
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Retourne {facet_name: (sql, binds)} pour les sous-requêtes de facettes."""

    def _clauses(skip: str) -> list[WhereClause | None]:
        return stats_filter_clauses(
            perimeter_structure_ids=perimeter_structure_ids,
            filters=filters,
            skip=skip,
        )

    year_where, year_binds = assemble_where(_clauses("year"))
    year_sql = f"""
        SELECT p.pub_year, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {STATS_BASE} AND {year_where}
          AND p.pub_year IS NOT NULL
        GROUP BY p.pub_year
        ORDER BY p.pub_year DESC
    """

    lab_where, lab_binds = assemble_where(_clauses("lab"))
    lab_sql = f"""
        SELECT s.id, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT a.publication_id) AS n
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        LEFT JOIN journals j ON j.id = p.journal_id
        JOIN authorship_structures aus ON aus.authorship_id = a.id
        JOIN structures s ON s.id = aus.structure_id
        WHERE {STATS_BASE} AND {lab_where}
          AND s.structure_type = '{StructureType.LABO.value}'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY n DESC
    """

    oa_where, oa_binds = assemble_where(_clauses("oa"))
    oa_sql = f"""
        SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {STATS_BASE} AND {oa_where}
          AND p.oa_status IS NOT NULL
        GROUP BY p.oa_status
        ORDER BY n DESC
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
        WHERE {STATS_BASE} AND {apc_where}
    """

    dt_where, dt_binds = assemble_where(_clauses("doc_type"))
    doc_type_sql = f"""
        SELECT p.doc_type::text AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {STATS_BASE} AND {dt_where}
        GROUP BY p.doc_type
        ORDER BY n DESC
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
    filters: StatsFilters,
) -> StatsFacetsResponse:
    """Décomptes de chaque facette, sa propre dimension écartée de la clause WHERE."""
    conn.execute(text("SET LOCAL jit = off"))
    sqls = _facets_sqls(
        perimeter_structure_ids=perimeter_structure_ids,
        filters=filters,
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
) -> StatsFacetsResponse:
    return StatsFacetsResponse(
        years=[FacetOption(value=str(r.pub_year), count=r.n) for r in year_rows],
        labs=[FacetOption(value=str(r.id), label=r.label, count=r.n) for r in lab_rows],
        oa_statuses=[FacetOption(value=r.value, count=r.n) for r in oa_rows],
        doc_types=[FacetOption(value=r.value, count=r.n) for r in doc_type_rows],
        apc=[
            FacetOption(value="uca", label="APC UCA", count=apc_row.apc_uca),
            FacetOption(value="non_uca", label="APC hors UCA", count=apc_row.apc_non_uca),
            FacetOption(value="none", label="Sans APC", count=apc_row.apc_none),
        ],
    )
