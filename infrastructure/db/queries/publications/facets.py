"""Facettes dynamiques pour /api/publications/facets.

Chaque facette exclut son propre filtre mais applique tous les autres.
Les facettes sont calculées en parallèle, chacune sur sa propre connexion
SA (les facettes sont indépendantes ; un même connecteur PG ne peut traiter
qu'une query à la fois).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.engine import get_async_engine
from infrastructure.db.queries.filters import (
    OA_CLOSED_SQL,
    OA_OPEN_SQL,
    PUB_IS_UCA,
    WhereClause,
    access_clause,
    apc_clause,
    assemble_where,
    corresponding_clause,
    country_clause,
    doc_type_clause,
    excluded_doc_type_clause,
    hal_status_clause,
    in_perimeter_person_clause,
    journal_id_clause,
    lab_clause,
    no_lab_clause,
    oa_clause,
    person_clause,
    publisher_id_clause,
    source_clause,
    subject_clause,
    year_clause,
)


@dataclass(frozen=True, slots=True)
class FacetFilters:
    """Bundle spécifique aux facettes (similaire à ListFilters mais sans
    pagination/sort)."""

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
    subject_id: int | None = None


class _PublicationFacetsBuilder:
    """Construit les facettes dynamiques pour /api/publications/facets.

    Chaque facette exclut son propre filtre mais applique tous les autres.
    Décomposition : une méthode privée par facette + un orchestrateur `build()`.
    """

    def __init__(
        self, conn: AsyncConnection, filters: FacetFilters, root_structure_id: int
    ) -> None:
        self.conn = conn
        self.filters = filters
        self.root_structure_id = root_structure_id
        self.lab_hal_col: Any = None

    # ── Utilitaires internes ────────────────────────────────────

    async def _preload_lab_hal_col(self) -> None:
        """Charge la hal_collection du labo (si un seul labo est sélectionné)."""
        if len(self.filters.lab_ids) == 1:
            row = (
                await self.conn.execute(
                    text("SELECT hal_collection FROM structures WHERE id = :sid"),
                    {"sid": self.filters.lab_ids[0]},
                )
            ).one_or_none()
            self.lab_hal_col = row.hal_collection if row else None

    def _base_clauses(self) -> list[WhereClause | None]:
        """Conditions de base : publications UCA ou par personne."""
        f = self.filters
        out: list[WhereClause | None] = []
        if f.person_id:
            out.append(WhereClause("p.doc_type NOT IN ('peer_review', 'memoir')", {}))
            out.append(person_clause(f.person_id))
        else:
            out.append(WhereClause(PUB_IS_UCA, {}))
        out.append(excluded_doc_type_clause(f.excluded_types))
        return out

    def _clauses_skipping(self, skip: str) -> tuple[str, dict[str, Any]]:  # noqa: C901
        """Conditions de base + tous les filtres sauf `skip`."""
        clauses: list[WhereClause | None] = list(self._base_clauses())
        f = self.filters
        if skip != "year":
            clauses.append(year_clause(f.years))
        if skip != "corresponding" and f.person_id:
            clauses.append(corresponding_clause(f.person_id, f.is_corresponding))
        if skip != "lab":
            if f.lab_none and not f.lab_ids:
                clauses.append(no_lab_clause())
            elif f.lab_ids:
                clauses.append(lab_clause(f.lab_ids))
        if skip != "doc_type":
            clauses.append(doc_type_clause(f.doc_types))
        if skip != "access":
            clauses.append(access_clause(f.access))
        if skip != "oa_status":
            clauses.append(oa_clause(f.oa_status))
        if skip != "source":
            clauses.append(source_clause(f.source_values))
        if skip != "apc":
            clauses.append(apc_clause(f.has_apc, self.root_structure_id, f.lab_ids))
        clauses.append(publisher_id_clause(f.publisher_id))
        clauses.append(journal_id_clause(f.journal_id))
        if skip != "country":
            clauses.append(country_clause(f.country_values))
        if skip != "hal_status":
            clauses.append(hal_status_clause(f.hal_status_values, self.lab_hal_col))
        if skip != "in_perimeter":
            clauses.append(in_perimeter_person_clause(f.in_perimeter, f.person_id))
        if skip != "subject":
            clauses.append(subject_clause(f.subject_id))
        return assemble_where(clauses)

    # ── Facettes ────────────────────────────────────────────────

    async def _facet_years(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("year")
        rows = (
            await self.conn.execute(
                text(f"""
                    SELECT p.pub_year AS value, COUNT(*) AS count
                    FROM publications p
                    WHERE {where_sql} AND p.pub_year IS NOT NULL
                    GROUP BY p.pub_year ORDER BY p.pub_year DESC
                """),
                binds,
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    async def _facet_labs(self) -> tuple[list[dict[str, Any]], int]:
        where_sql, binds = self._clauses_skipping("lab")
        labs_rows = (
            await self.conn.execute(
                text(f"""
                    SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
                           COUNT(DISTINCT a.publication_id) AS count
                    FROM authorships a
                    JOIN publications p ON p.id = a.publication_id
                    CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
                    JOIN structures s ON s.id = struct_id
                    WHERE {where_sql}
                      AND s.structure_type = 'labo'
                    GROUP BY s.id, s.acronym, s.name
                    ORDER BY count DESC
                """),
                binds,
            )
        ).all()
        labs = [dict(r._mapping) for r in labs_rows]

        no_lab_row = (
            await self.conn.execute(
                text(f"""
                    SELECT COUNT(*) AS total FROM publications p
                    WHERE {where_sql}
                      AND NOT EXISTS (
                          SELECT 1 FROM authorships a
                          JOIN structures s ON s.id = ANY(a.structure_ids)
                          WHERE a.publication_id = p.id
                            AND NOT a.excluded
                            AND s.structure_type = 'labo'
                      )
                """),
                binds,
            )
        ).one()
        return labs, no_lab_row.total

    async def _facet_doc_types(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("doc_type")
        rows = (
            await self.conn.execute(
                text(f"""
                    SELECT p.doc_type::text AS value, COUNT(*) AS count
                    FROM publications p
                    WHERE {where_sql} AND p.doc_type IS NOT NULL
                    GROUP BY p.doc_type ORDER BY count DESC
                """),
                binds,
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    async def _facet_access(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("access")
        r = (
            await self.conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE p.oa_status::text IN {OA_OPEN_SQL}) AS open_count,
                        COUNT(*) FILTER (
                            WHERE p.oa_status::text IN {OA_CLOSED_SQL}
                               OR p.oa_status IS NULL
                        ) AS closed_count
                    FROM publications p
                    WHERE {where_sql}
                """),
                binds,
            )
        ).one()
        return [
            {"value": "open", "text": "Ouvert", "count": r.open_count},
            {"value": "closed", "text": "Fermé", "count": r.closed_count},
        ]

    async def _facet_oa_statuses(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("oa_status")
        rows = (
            await self.conn.execute(
                text(f"""
                    SELECT p.oa_status::text AS value, COUNT(*) AS count
                    FROM publications p
                    WHERE {where_sql} AND p.oa_status IS NOT NULL
                    GROUP BY p.oa_status ORDER BY count DESC
                """),
                binds,
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    async def _facet_corresponding(self) -> list[dict[str, Any]]:
        if not self.filters.person_id:
            return []
        where_sql, binds = self._clauses_skipping("corresponding")
        row = (
            await self.conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM authorships a
                            WHERE a.publication_id = p.id AND a.person_id = :corr_pid
                              AND a.is_corresponding = TRUE AND NOT a.excluded
                        )) AS yes_count,
                        COUNT(*) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM authorships a
                            WHERE a.publication_id = p.id AND a.person_id = :corr_pid
                              AND a.is_corresponding = TRUE AND NOT a.excluded
                        )) AS no_count
                    FROM publications p
                    WHERE {where_sql}
                """),
                {**binds, "corr_pid": self.filters.person_id},
            )
        ).one()
        return [
            {"value": "yes", "count": row.yes_count},
            {"value": "no", "count": row.no_count},
        ]

    async def _facet_source_counts(self) -> dict[str, dict[str, int]]:
        """Counts {yes, no} par source, ignorant en bloc tous les filtres source."""
        where_sql, binds = self._clauses_skipping("source")
        row = (
            await self.conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE p.sources @> ARRAY['hal'::source_type]) AS hal_yes,
                        COUNT(*) FILTER (WHERE NOT p.sources @> ARRAY['hal'::source_type]) AS hal_no,
                        COUNT(*) FILTER (WHERE p.sources @> ARRAY['openalex'::source_type]) AS oa_yes,
                        COUNT(*) FILTER (WHERE NOT p.sources @> ARRAY['openalex'::source_type]) AS oa_no,
                        COUNT(*) FILTER (WHERE p.sources @> ARRAY['scanr'::source_type]) AS scanr_yes,
                        COUNT(*) FILTER (WHERE NOT p.sources @> ARRAY['scanr'::source_type]) AS scanr_no,
                        COUNT(*) FILTER (WHERE p.sources @> ARRAY['wos'::source_type]) AS wos_yes,
                        COUNT(*) FILTER (WHERE NOT p.sources @> ARRAY['wos'::source_type]) AS wos_no,
                        COUNT(*) FILTER (WHERE p.sources @> ARRAY['theses'::source_type]) AS theses_yes,
                        COUNT(*) FILTER (WHERE NOT p.sources @> ARRAY['theses'::source_type]) AS theses_no
                    FROM publications p
                    WHERE {where_sql}
                """),
                binds,
            )
        ).one()
        return {
            "hal": {"yes": row.hal_yes, "no": row.hal_no},
            "oa": {"yes": row.oa_yes, "no": row.oa_no},
            "scanr": {"yes": row.scanr_yes, "no": row.scanr_no},
            "wos": {"yes": row.wos_yes, "no": row.wos_no},
            "theses": {"yes": row.theses_yes, "no": row.theses_no},
        }

    async def _facet_apc(self) -> list[dict[str, Any]]:
        """APC : variante à 4 catégories si un labo est sélectionné, sinon 3."""
        where_sql, binds = self._clauses_skipping("apc")
        if self.filters.lab_ids:
            return await self._facet_apc_with_lab(where_sql, binds)
        return await self._facet_apc_without_lab(where_sql, binds)

    async def _facet_apc_with_lab(self, where: str, binds: dict[str, Any]) -> list[dict[str, Any]]:
        lab_ids = self.filters.lab_ids
        r = (
            await self.conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM apc_payments ap
                            WHERE ap.publication_id = p.id
                              AND ap.lab_structure_id = ANY(CAST(:apc_facet_lab_ids AS int[]))
                        )) AS apc_this_lab,
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM apc_payments ap
                            WHERE ap.publication_id = p.id
                              AND ap.budget_structure_id = :apc_facet_root
                        ) AND NOT EXISTS (
                            SELECT 1 FROM apc_payments ap
                            WHERE ap.publication_id = p.id
                              AND ap.lab_structure_id = ANY(CAST(:apc_facet_lab_ids AS int[]))
                        )) AS apc_other_uca,
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                        ) AND NOT EXISTS (
                            SELECT 1 FROM apc_payments ap
                            WHERE ap.publication_id = p.id
                              AND ap.budget_structure_id = :apc_facet_root
                        )) AS apc_non_uca,
                        COUNT(*) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                        )) AS apc_none
                    FROM publications p
                    WHERE {where}
                """),
                {
                    **binds,
                    "apc_facet_lab_ids": lab_ids,
                    "apc_facet_root": self.root_structure_id,
                },
            )
        ).one()
        label_row = (
            await self.conn.execute(
                text("SELECT COALESCE(acronym, name) AS label FROM structures WHERE id = :id"),
                {"id": lab_ids[0]},
            )
        ).one_or_none()
        lab_label = label_row.label if label_row else "ce labo"
        return [
            {"value": "this_lab", "text": f"APC — {lab_label}", "count": r.apc_this_lab},
            {"value": "other_uca", "text": "APC — autres UCA", "count": r.apc_other_uca},
            {"value": "non_uca", "text": "APC hors UCA", "count": r.apc_non_uca},
            {"value": "none", "text": "Sans APC", "count": r.apc_none},
        ]

    async def _facet_apc_without_lab(
        self, where: str, binds: dict[str, Any]
    ) -> list[dict[str, Any]]:
        r = (
            await self.conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM apc_payments ap
                            WHERE ap.publication_id = p.id
                              AND ap.budget_structure_id = :apc_facet_root
                        )) AS apc_uca,
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                        ) AND NOT EXISTS (
                            SELECT 1 FROM apc_payments ap
                            WHERE ap.publication_id = p.id
                              AND ap.budget_structure_id = :apc_facet_root
                        )) AS apc_other,
                        COUNT(*) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                        )) AS apc_none
                    FROM publications p
                    WHERE {where}
                """),
                {**binds, "apc_facet_root": self.root_structure_id},
            )
        ).one()
        return [
            {"value": "uca", "text": "APC — UCA", "count": r.apc_uca},
            {"value": "other", "text": "APC — autres", "count": r.apc_other},
            {"value": "none", "text": "Sans APC", "count": r.apc_none},
        ]

    async def _facet_countries(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("country")
        rows = (
            await self.conn.execute(
                text(f"""
                    SELECT co.code, co.name, COUNT(*) AS count
                    FROM (
                        SELECT unnest(p.countries) AS cc
                        FROM publications p
                        WHERE {where_sql} AND p.countries IS NOT NULL
                    ) sub
                    JOIN countries co ON co.code = sub.cc
                    GROUP BY co.code, co.name
                    ORDER BY count DESC
                """),
                binds,
            )
        ).all()
        return [
            {"value": r.code.strip(), "text": r.name, "count": r.count}
            for r in rows
            if r.code.strip() != "xx"
        ]

    async def _facet_hal_status(self) -> list[dict[str, Any]]:
        """HAL status : seulement si un seul labo est sélectionné."""
        if len(self.filters.lab_ids) != 1:
            return []
        where_sql, binds = self._clauses_skipping("hal_status")
        col = self.lab_hal_col
        if col:
            r = (
                await self.conn.execute(
                    text(f"""
                        SELECT
                            COUNT(*) FILTER (WHERE NOT EXISTS (
                                SELECT 1 FROM source_publications sd
                                WHERE sd.publication_id = p.id AND sd.source = 'hal'
                            )) AS hors_hal,
                            COUNT(*) FILTER (WHERE EXISTS (
                                SELECT 1 FROM source_publications sd
                                WHERE sd.publication_id = p.id AND sd.source = 'hal'
                            ) AND NOT EXISTS (
                                SELECT 1 FROM source_publications sd
                                WHERE sd.publication_id = p.id AND sd.source = 'hal'
                                  AND sd.hal_collections @> ARRAY[:hf_col]
                            )) AS hors_collection,
                            COUNT(*) FILTER (WHERE EXISTS (
                                SELECT 1 FROM source_publications sd
                                WHERE sd.publication_id = p.id AND sd.source = 'hal'
                                  AND sd.hal_collections @> ARRAY[:hf_col]
                            ) AND (p.oa_status IS NULL OR p.oa_status::text IN {OA_CLOSED_SQL})
                            ) AS notice,
                            COUNT(*) FILTER (WHERE EXISTS (
                                SELECT 1 FROM source_publications sd
                                WHERE sd.publication_id = p.id AND sd.source = 'hal'
                                  AND sd.hal_collections @> ARRAY[:hf_col]
                            ) AND p.oa_status IS NOT NULL
                              AND p.oa_status::text NOT IN {OA_CLOSED_SQL}
                            ) AS ok
                        FROM publications p
                        WHERE {where_sql}
                    """),
                    {**binds, "hf_col": col},
                )
            ).one()
        else:
            r = (
                await self.conn.execute(
                    text(f"""
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
                        WHERE {where_sql}
                    """),
                    binds,
                )
            ).one()
        return [
            {"value": "ok", "text": "OK", "count": r.ok},
            {"value": "notice", "text": "Notice", "count": r.notice},
            {"value": "hors_collection", "text": "Hors collection", "count": r.hors_collection},
            {"value": "hors_hal", "text": "Hors HAL", "count": r.hors_hal},
        ]

    async def _facet_in_perimeter(self) -> list[dict[str, Any]]:
        if not self.filters.person_id:
            return []
        where_sql, binds = self._clauses_skipping("in_perimeter")
        r = (
            await self.conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM authorships a
                            WHERE a.publication_id = p.id AND a.person_id = :inp_pid
                              AND a.in_perimeter = TRUE AND NOT a.excluded
                        )) AS yes,
                        COUNT(*) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM authorships a
                            WHERE a.publication_id = p.id AND a.person_id = :inp_pid
                              AND a.in_perimeter = TRUE AND NOT a.excluded
                        )) AS no
                    FROM publications p
                    WHERE {where_sql}
                """),
                {**binds, "inp_pid": self.filters.person_id},
            )
        ).one()
        return [
            {"value": "yes", "text": "UCA", "count": r.yes},
            {"value": "no", "text": "Hors périmètre", "count": r.no},
        ]


async def publications_facets(
    conn: AsyncConnection, *, filters: FacetFilters, root_structure_id: int
) -> dict[str, Any]:
    """Facettes dynamiques : chaque facette exclut son propre filtre mais
    applique tous les autres.

    Les facettes sont indépendantes — on les calcule en parallèle, chacune
    sur sa propre AsyncConnection (l'engine SA gère le pool sous le capot).
    Le `conn` passé en argument sert uniquement au préchargement de
    `lab_hal_col` (lookup unique).
    """
    preload = _PublicationFacetsBuilder(conn, filters, root_structure_id)
    await preload._preload_lab_hal_col()
    lab_hal_col = preload.lab_hal_col

    engine = get_async_engine()

    async def run(facet: Callable[[_PublicationFacetsBuilder], Awaitable[Any]]) -> Any:
        async with engine.begin() as facet_conn:
            await facet_conn.execute(text("SET LOCAL jit = off"))
            b = _PublicationFacetsBuilder(facet_conn, filters, root_structure_id)
            b.lab_hal_col = lab_hal_col
            return await facet(b)

    (
        years,
        labs_pair,
        doc_types,
        access,
        oa_statuses,
        corresponding,
        source_counts,
        apc,
        countries,
        hal_status,
        in_perimeter,
    ) = await asyncio.gather(
        run(lambda b: b._facet_years()),
        run(lambda b: b._facet_labs()),
        run(lambda b: b._facet_doc_types()),
        run(lambda b: b._facet_access()),
        run(lambda b: b._facet_oa_statuses()),
        run(lambda b: b._facet_corresponding()),
        run(lambda b: b._facet_source_counts()),
        run(lambda b: b._facet_apc()),
        run(lambda b: b._facet_countries()),
        run(lambda b: b._facet_hal_status()),
        run(lambda b: b._facet_in_perimeter()),
    )
    labs, no_lab_count = labs_pair

    return {
        "years": years,
        "labs": labs,
        "no_lab_count": no_lab_count,
        "doc_types": doc_types,
        "access": access,
        "oa_statuses": oa_statuses,
        "corresponding": corresponding,
        "source_counts": source_counts,
        "apc": apc,
        "countries": countries,
        "hal_status": hal_status,
        "in_perimeter": in_perimeter,
    }
