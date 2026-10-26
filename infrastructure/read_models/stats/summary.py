"""Années disponibles et facettes croisées des statistiques."""

from collections.abc import Sequence

from sqlalchemy import Connection, Row, text

from domain.publications.licenses import license_label
from domain.structures.structure import StructureType
from infrastructure.read_models._common import FacetOption
from infrastructure.read_models.filters import (
    WhereClause,
    assemble_where,
    institution_apc_payment_sql,
)
from infrastructure.read_models.perimeters.queries import get_persons_perimeter_name
from infrastructure.read_models.publications.models import NO_LICENSE
from infrastructure.read_models.stats._shared import STATS_BASE, stats_filter_clauses
from infrastructure.read_models.stats.models import StatsFacetsResponse, StatsFilters


def _facets_sqls(
    *,
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
) -> dict[str, tuple[str, dict[str, object]]]:
    """Retourne {facet_name: (sql, binds)} pour les sous-requêtes de facettes."""

    def _clauses(skip: str) -> list[WhereClause | None]:
        return stats_filter_clauses(
            perimeter_structure_ids=perimeter_structure_ids,
            filters=filters,
            skip=skip,
        )

    year_where, year_binds = assemble_where(_clauses("year"))
    year_sql = f"""
        SELECT p.publication_year, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {STATS_BASE} AND {year_where}
          AND p.publication_year IS NOT NULL
        GROUP BY p.publication_year
        ORDER BY p.publication_year DESC
    """

    lab_where, lab_binds = assemble_where(_clauses("lab"))
    lab_sql = f"""
        SELECT s.id, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT p.id) AS n
        FROM publication_structures ps
        JOIN publications p ON p.id = ps.publication_id
        LEFT JOIN serials j ON j.id = p.serial_id
        JOIN structures s ON s.id = ps.structure_id
        WHERE {STATS_BASE} AND {lab_where}
          AND s.structure_type = '{StructureType.LABO.value}'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY n DESC
    """

    oa_where, oa_binds = assemble_where(_clauses("oa"))
    oa_sql = f"""
        SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {STATS_BASE} AND {oa_where}
          AND p.oa_status IS NOT NULL
        GROUP BY p.oa_status
        ORDER BY n DESC
    """

    apc_where, apc_binds = assemble_where(_clauses("apc"))
    paid = institution_apc_payment_sql("apc_root_ids")
    apc_sql = f"""
        SELECT
            COUNT(DISTINCT p.id) FILTER (WHERE {paid}) AS apc_yes,
            COUNT(DISTINCT p.id) FILTER (WHERE NOT {paid}) AS apc_no
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {STATS_BASE} AND {apc_where}
    """

    dt_where, dt_binds = assemble_where(_clauses("doc_type"))
    doc_type_sql = f"""
        SELECT p.doc_type::text AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {STATS_BASE} AND {dt_where}
        GROUP BY p.doc_type
        ORDER BY n DESC
    """

    license_where, license_binds = assemble_where(_clauses("license"))
    license_sql = f"""
        SELECT COALESCE(p.license::text, '{NO_LICENSE}') AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {STATS_BASE} AND {license_where}
        GROUP BY 1
        ORDER BY n DESC
    """

    return {
        "year": (year_sql, year_binds),
        "lab": (lab_sql, lab_binds),
        "oa": (oa_sql, oa_binds),
        "license": (license_sql, license_binds),
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
    license_rows = conn.execute(text(sqls["license"][0]), sqls["license"][1]).all()

    return _build_facets_result(
        year_rows,
        lab_rows,
        oa_rows,
        apc_row,
        doc_type_rows,
        license_rows=license_rows,
        institution=get_persons_perimeter_name(conn),
    )


def _build_facets_result(
    year_rows: Sequence[Row[tuple[object, ...]]],
    lab_rows: Sequence[Row[tuple[object, ...]]],
    oa_rows: Sequence[Row[tuple[object, ...]]],
    apc_row: Row[tuple[object, ...]],
    doc_type_rows: Sequence[Row[tuple[object, ...]]],
    *,
    institution: str,
    license_rows: Sequence[Row[tuple[object, ...]]] = (),
) -> StatsFacetsResponse:
    return StatsFacetsResponse(
        years=[FacetOption(value=str(r.publication_year), count=r.n) for r in year_rows],
        labs=[FacetOption(value=str(r.id), label=r.label, count=r.n) for r in lab_rows],
        oa_statuses=[FacetOption(value=r.value, count=r.n) for r in oa_rows],
        licenses=[
            FacetOption(
                value=r.value,
                label=license_label(None if r.value == NO_LICENSE else r.value),
                count=r.n,
            )
            for r in license_rows
        ],
        doc_types=[FacetOption(value=r.value, count=r.n) for r in doc_type_rows],
        apc=[
            FacetOption(value="yes", label=f"APC {institution}", count=apc_row.apc_yes),
            FacetOption(value="no", label="Sans APC", count=apc_row.apc_no),
        ],
    )
