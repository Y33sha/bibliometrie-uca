"""Résumé global, ventilation annuelle, années disponibles, facettes croisées (async)."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.queries.filters import (
    PUB_IS_UCA,
    WhereClause,
    assemble_where,
    lab_clause,
    oa_clause,
    year_clause,
)
from infrastructure.db.queries.stats._shared import stats_apc_clause

_BASE_CLAUSES = " AND ".join(
    [
        PUB_IS_UCA,
        "p.doc_type IN ('article', 'review')",
        "(j.oa_model IS DISTINCT FROM 'repository')",
    ]
)


def _publisher_journal_clauses(
    publisher_id: int | None, journal_id: int | None
) -> list[WhereClause | None]:
    out: list[WhereClause | None] = []
    if publisher_id:
        out.append(
            WhereClause("j.publisher_id = :flt_publisher_id", {"flt_publisher_id": publisher_id})
        )
    if journal_id:
        out.append(WhereClause("p.journal_id = :flt_journal_id", {"flt_journal_id": journal_id}))
    return out


def _common_clauses(
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
    skip: str = "",
) -> list[WhereClause | None]:
    """Construit les filtres communs aux endpoints stats summary / facets.

    `skip` permet d'omettre un filtre pour les facettes croisées ("year",
    "lab", "oa", "apc"). Les filtres publisher/journal sont toujours
    appliqués (jamais facettés).
    """
    out: list[WhereClause | None] = []
    if skip != "year":
        out.append(year_clause(years))
    if skip != "lab":
        out.append(lab_clause(lab_ids))
    out.extend(_publisher_journal_clauses(publisher_id, journal_id))
    if skip != "oa":
        out.append(oa_clause(oa_status))
    if skip != "apc":
        out.append(stats_apc_clause(has_apc, root_structure_id))
    return out


async def stats_by_year(
    conn: AsyncConnection,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
) -> list[dict[str, Any]]:
    """Ventilation par année (articles + review, périmètre UCA)."""
    await conn.execute(text("SET LOCAL jit = off"))
    dyn_where, binds = assemble_where(
        _common_clauses(
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
        )
    )
    rows = (
        await conn.execute(
            text(f"""
                SELECT
                    p.pub_year,
                    COUNT(DISTINCT p.id) AS pub_count,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'diamond') AS diamond,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE {_BASE_CLAUSES} AND {dyn_where}
                GROUP BY p.pub_year
                ORDER BY p.pub_year
            """),
            binds,
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def stats_summary(
    conn: AsyncConnection,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
) -> dict[str, Any]:
    """Totaux globaux pour la page stats."""
    await conn.execute(text("SET LOCAL jit = off"))
    dyn_where, binds = assemble_where(
        _common_clauses(
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
        )
    )
    row = (
        await conn.execute(
            text(f"""
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
                WHERE {_BASE_CLAUSES} AND {dyn_where}
            """),
            binds,
        )
    ).one()
    return dict(row._mapping)


async def available_years(conn: AsyncConnection) -> list[int]:
    """Liste des années de publication disponibles (périmètre UCA)."""
    await conn.execute(text("SET LOCAL jit = off"))
    rows = (
        await conn.execute(
            text(f"""
                SELECT DISTINCT pub_year FROM publications p
                WHERE {PUB_IS_UCA} AND pub_year IS NOT NULL
                ORDER BY pub_year DESC
            """)
        )
    ).all()
    return [r.pub_year for r in rows]


async def stats_facets(
    conn: AsyncConnection,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
) -> dict[str, list[dict[str, Any]]]:
    """Facettes dynamiques (années, labos, oa_status, apc) : chaque facette
    exclut son propre filtre mais applique tous les autres."""
    await conn.execute(text("SET LOCAL jit = off"))

    def _clauses(skip: str) -> list[WhereClause | None]:
        return _common_clauses(
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
            skip=skip,
        )

    # --- ANNÉES ---
    year_where, year_binds = assemble_where(_clauses("year"))
    year_rows = (
        await conn.execute(
            text(f"""
                SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE {_BASE_CLAUSES} AND {year_where}
                  AND p.pub_year IS NOT NULL
                GROUP BY p.pub_year
                ORDER BY p.pub_year DESC
            """),
            year_binds,
        )
    ).all()
    year_facets = [{"value": r.pub_year, "count": r.count} for r in year_rows]

    # --- LABOS ---
    lab_where, lab_binds = assemble_where(_clauses("lab"))
    lab_rows = (
        await conn.execute(
            text(f"""
                SELECT s.id, COALESCE(s.acronym, s.name) AS label,
                       COUNT(DISTINCT a.publication_id) AS count
                FROM authorships a
                JOIN publications p ON p.id = a.publication_id
                LEFT JOIN journals j ON j.id = p.journal_id
                CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
                JOIN structures s ON s.id = struct_id
                WHERE {_BASE_CLAUSES} AND {lab_where}
                  AND s.structure_type = 'labo'
                GROUP BY s.id, s.acronym, s.name
                ORDER BY count DESC
            """),
            lab_binds,
        )
    ).all()
    lab_facets = [{"value": r.id, "label": r.label, "count": r.count} for r in lab_rows]

    # --- OA ---
    oa_where, oa_binds = assemble_where(_clauses("oa"))
    oa_rows = (
        await conn.execute(
            text(f"""
                SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS count
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE {_BASE_CLAUSES} AND {oa_where}
                  AND p.oa_status IS NOT NULL
                GROUP BY p.oa_status
                ORDER BY count DESC
            """),
            oa_binds,
        )
    ).all()
    oa_facets = [{"value": r.value, "count": r.count} for r in oa_rows]

    # --- APC ---
    apc_where, apc_binds = assemble_where(_clauses("apc"))
    apc_row = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id
                          AND ap.budget_structure_id = :apc_root
                    )) AS apc_uca,
                    COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                    ) AND NOT EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id
                          AND ap.budget_structure_id = :apc_root
                    )) AS apc_non_uca,
                    COUNT(DISTINCT p.id) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                    )) AS apc_none
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE {_BASE_CLAUSES} AND {apc_where}
            """),
            {**apc_binds, "apc_root": root_structure_id},
        )
    ).one()
    apc_facets = [
        {"value": "uca", "text": "APC UCA", "count": apc_row.apc_uca},
        {"value": "non_uca", "text": "APC hors UCA", "count": apc_row.apc_non_uca},
        {"value": "none", "text": "Sans APC", "count": apc_row.apc_none},
    ]

    return {
        "years": year_facets,
        "labs": lab_facets,
        "oa_statuses": oa_facets,
        "apc": apc_facets,
    }
