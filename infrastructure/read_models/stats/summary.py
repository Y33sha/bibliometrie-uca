"""Années disponibles et facettes croisées des statistiques."""

from collections.abc import Sequence

from sqlalchemy import Connection, Row, text

from domain.publications.licenses import license_label
from domain.structures.structure import StructureType
from infrastructure.read_models._common import FacetOption
from infrastructure.read_models.filters import institution_apc_payment_sql
from infrastructure.read_models.perimeters.queries import get_persons_perimeter_name
from infrastructure.read_models.publications.filtering import (
    FilterContext,
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import NO_LICENSE, PublicationFilters
from infrastructure.read_models.stats.models import StatsFacetsResponse


def _facets_sqls(
    *,
    context: FilterContext,
    filters: PublicationFilters,
) -> dict[str, tuple[str, dict[str, object]]]:
    """Retourne {facet_name: (sql, binds)} pour les sous-requêtes de facettes."""

    year_where, year_binds = publication_filter_where(filters, context, "year")
    year_sql = f"""
        SELECT p.publication_year, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {year_where}
          AND p.publication_year IS NOT NULL
        GROUP BY p.publication_year
        ORDER BY p.publication_year DESC
    """

    lab_where, lab_binds = publication_filter_where(filters, context, "lab")
    lab_sql = f"""
        SELECT s.id, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT p.id) AS n
        FROM publication_structures ps
        JOIN publications p ON p.id = ps.publication_id
        LEFT JOIN serials j ON j.id = p.serial_id
        JOIN structures s ON s.id = ps.structure_id
        WHERE {lab_where}
          AND s.structure_type = '{StructureType.LABO.value}'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY n DESC
    """

    oa_where, oa_binds = publication_filter_where(filters, context, "oa_status")
    oa_sql = f"""
        SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {oa_where}
          AND p.oa_status IS NOT NULL
        GROUP BY p.oa_status
        ORDER BY n DESC
    """

    apc_where, apc_binds = publication_filter_where(filters, context, "apc")
    paid = institution_apc_payment_sql("apc_root_ids")
    apc_sql = f"""
        SELECT
            COUNT(DISTINCT p.id) FILTER (WHERE {paid}) AS apc_yes,
            COUNT(DISTINCT p.id) FILTER (WHERE NOT {paid}) AS apc_no
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {apc_where}
    """

    dt_where, dt_binds = publication_filter_where(filters, context, "doc_type")
    doc_type_sql = f"""
        SELECT p.doc_type::text AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {dt_where}
        GROUP BY p.doc_type
        ORDER BY n DESC
    """

    license_where, license_binds = publication_filter_where(filters, context, "license")
    license_sql = f"""
        SELECT COALESCE(p.license::text, '{NO_LICENSE}') AS value, COUNT(DISTINCT p.id) AS n
        FROM publications p
        LEFT JOIN serials j ON j.id = p.serial_id
        WHERE {license_where}
        GROUP BY 1
        ORDER BY n DESC
    """

    return {
        "year": (year_sql, year_binds),
        "lab": (lab_sql, lab_binds),
        "oa": (oa_sql, oa_binds),
        "license": (license_sql, license_binds),
        "apc": (apc_sql, {**apc_binds, "apc_root_ids": context.perimeter_structure_ids}),
        "doc_type": (doc_type_sql, dt_binds),
    }


class StatsFacetQueries:
    _conn: Connection

    def stats_facets(self, *, filters: PublicationFilters) -> StatsFacetsResponse:
        """Décomptes de chaque facette, sa propre dimension écartée de la clause WHERE."""
        self._conn.execute(text("SET LOCAL jit = off"))
        sqls = _facets_sqls(
            context=filter_context(self._conn, filters),
            filters=filters,
        )
        rows = {
            name: self._conn.execute(text(sql), binds).all() for name, (sql, binds) in sqls.items()
        }
        return _build_facets_result(
            rows["year"],
            rows["lab"],
            rows["oa"],
            rows["apc"][0],
            rows["doc_type"],
            license_rows=rows["license"],
            institution=get_persons_perimeter_name(self._conn),
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
