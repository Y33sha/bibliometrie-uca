"""Facettes dynamiques pour /api/publications/facets.

Chaque facette exclut son propre filtre mais applique tous les autres.
Les facettes sont calculées en parallèle, chacune sur sa propre connexion
du pool async (les facettes sont indépendantes ; un même connecteur PG ne
peut traiter qu'une query à la fois).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from infrastructure.db.async_connection import get_async_pool
from infrastructure.db.queries.filters import (
    OA_CLOSED_SQL,
    OA_OPEN_SQL,
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
    subject_id: int | None = None


class _PublicationFacetsBuilder:
    """Construit les facettes dynamiques pour /api/publications/facets.

    Chaque facette exclut son propre filtre mais applique tous les autres.
    Décomposition : une méthode privée par facette + un orchestrateur `build()`.
    """

    def __init__(self, cur: Any, filters: FacetFilters, root_structure_id: int) -> None:
        self.cur = cur
        self.filters = filters
        self.root_structure_id = root_structure_id
        self.lab_hal_col: Any = None

    # ── Utilitaires internes ────────────────────────────────────

    async def _preload_lab_hal_col(self) -> None:
        """Charge la hal_collection du labo (si un seul labo est sélectionné)."""
        if len(self.filters.lab_ids) == 1:
            await self.cur.execute(
                "SELECT hal_collection FROM structures WHERE id = %s",
                (self.filters.lab_ids[0],),
            )
            row = await self.cur.fetchone()
            self.lab_hal_col = row["hal_collection"] if row else None

    def _base_conds(self) -> tuple[list[str], list[Any]]:
        """Conditions de base : publications UCA ou par personne."""
        f = self.filters
        if f.person_id:
            c: list[str] = ["p.doc_type NOT IN ('peer_review', 'memoir')"]
            p: list[Any] = []
            apply_person_filter(c, p, f.person_id)
        else:
            c, p = [PUB_IS_UCA], []
        if f.excluded_types:
            c.append("p.doc_type::text != ALL(%s)")
            p.append(f.excluded_types)
        return c, p

    def _conds_skipping(self, skip: str) -> tuple[list[str], list[Any]]:  # noqa: C901
        """Conditions de base + tous les filtres sauf `skip`."""
        conds, params = self._base_conds()
        f = self.filters
        if skip != "year":
            apply_year_filter(conds, params, f.years)
        if skip != "corresponding" and f.person_id:
            apply_corresponding_filter(conds, params, f.person_id, f.is_corresponding)
        if skip != "lab":
            if f.lab_none and not f.lab_ids:
                apply_no_lab_filter(conds, params)
            elif f.lab_ids:
                apply_lab_filter(conds, params, f.lab_ids)
        if skip != "doc_type":
            apply_doc_type_filter(conds, params, f.doc_types)
        if skip != "access":
            apply_access_filter(conds, params, f.access)
        if skip != "oa_status":
            apply_oa_filter(conds, params, f.oa_status)
        if skip != "source":
            apply_source_filter(conds, f.source_values)
        if skip != "apc":
            apply_apc_filter(conds, params, f.has_apc, self.root_structure_id, lab_ids=f.lab_ids)
        apply_publisher_journal_filter(conds, params, f.publisher_id, f.journal_id)
        if skip != "country" and f.country_values:
            conds.append("p.countries && %s::text[]")
            params.append(f.country_values)
        if skip != "hal_status":
            apply_hal_status_filter(conds, params, f.hal_status_values, self.lab_hal_col)
        if skip != "in_perimeter":
            apply_in_perimeter_person_filter(conds, params, f.in_perimeter, f.person_id)
        if skip != "subject" and f.subject_id:
            conds.append(
                "EXISTS (SELECT 1 FROM publication_subjects ps "
                "WHERE ps.publication_id = p.id AND ps.subject_id = %s)"
            )
            params.append(f.subject_id)
        return conds, params

    @staticmethod
    def _where_sql(conds: list[str]) -> str:
        return " AND ".join(conds) if conds else "TRUE"

    # ── Facettes ────────────────────────────────────────────────

    async def _facet_years(self) -> list[dict[str, Any]]:
        c, p = self._conds_skipping("year")
        await self.cur.execute(
            f"""
            SELECT p.pub_year AS value, COUNT(*) AS count
            FROM publications p
            WHERE {self._where_sql(c)} AND p.pub_year IS NOT NULL
            GROUP BY p.pub_year ORDER BY p.pub_year DESC
            """,
            p,
        )
        return await self.cur.fetchall()

    async def _facet_labs(self) -> tuple[list[dict[str, Any]], int]:
        c, p = self._conds_skipping("lab")
        await self.cur.execute(
            f"""
            SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
                   COUNT(DISTINCT a.publication_id) AS count
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
            JOIN structures s ON s.id = struct_id
            WHERE {self._where_sql(c)}
              AND s.structure_type = 'labo'
            GROUP BY s.id, s.acronym, s.name
            ORDER BY count DESC
            """,
            p,
        )
        labs = await self.cur.fetchall()

        await self.cur.execute(
            f"""
            SELECT COUNT(*) AS count FROM publications p
            WHERE {self._where_sql(c)}
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
        row = await self.cur.fetchone()
        no_lab_count = row["count"]
        return labs, no_lab_count

    async def _facet_doc_types(self) -> list[dict[str, Any]]:
        c, p = self._conds_skipping("doc_type")
        await self.cur.execute(
            f"""
            SELECT p.doc_type::text AS value, COUNT(*) AS count
            FROM publications p
            WHERE {self._where_sql(c)} AND p.doc_type IS NOT NULL
            GROUP BY p.doc_type ORDER BY count DESC
            """,
            p,
        )
        return await self.cur.fetchall()

    async def _facet_access(self) -> list[dict[str, Any]]:
        c, p = self._conds_skipping("access")
        await self.cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE p.oa_status::text IN {OA_OPEN_SQL}) AS open_count,
                COUNT(*) FILTER (WHERE p.oa_status::text IN {OA_CLOSED_SQL} OR p.oa_status IS NULL) AS closed_count
            FROM publications p
            WHERE {self._where_sql(c)}
            """,
            p,
        )
        r = await self.cur.fetchone()
        return [
            {"value": "open", "text": "Ouvert", "count": r["open_count"]},
            {"value": "closed", "text": "Fermé", "count": r["closed_count"]},
        ]

    async def _facet_oa_statuses(self) -> list[dict[str, Any]]:
        c, p = self._conds_skipping("oa_status")
        await self.cur.execute(
            f"""
            SELECT p.oa_status::text AS value, COUNT(*) AS count
            FROM publications p
            WHERE {self._where_sql(c)} AND p.oa_status IS NOT NULL
            GROUP BY p.oa_status ORDER BY count DESC
            """,
            p,
        )
        return await self.cur.fetchall()

    async def _facet_corresponding(self) -> list[dict[str, Any]]:
        if not self.filters.person_id:
            return []
        c, p = self._conds_skipping("corresponding")
        await self.cur.execute(
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
            WHERE {self._where_sql(c)}
            """,
            [self.filters.person_id, self.filters.person_id] + p,
        )
        row = await self.cur.fetchone()
        return [
            {"value": "yes", "count": row["yes_count"]},
            {"value": "no", "count": row["no_count"]},
        ]

    async def _facet_source_counts(self) -> dict[str, dict[str, int]]:
        """Counts {yes, no} par source, ignorant en bloc tous les filtres source."""
        c, p = self._conds_skipping("source")
        await self.cur.execute(
            f"""
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
            WHERE {self._where_sql(c)}
            """,
            p,
        )
        row = await self.cur.fetchone()
        return {
            "hal": {"yes": row["hal_yes"], "no": row["hal_no"]},
            "oa": {"yes": row["oa_yes"], "no": row["oa_no"]},
            "scanr": {"yes": row["scanr_yes"], "no": row["scanr_no"]},
            "wos": {"yes": row["wos_yes"], "no": row["wos_no"]},
            "theses": {"yes": row["theses_yes"], "no": row["theses_no"]},
        }

    async def _facet_apc(self) -> list[dict[str, Any]]:
        """APC : variante à 4 catégories si un labo est sélectionné, sinon 3."""
        c, p = self._conds_skipping("apc")
        where = self._where_sql(c)
        if self.filters.lab_ids:
            return await self._facet_apc_with_lab(where, p)
        return await self._facet_apc_without_lab(where, p)

    async def _facet_apc_with_lab(self, where: str, p: list[Any]) -> list[dict[str, Any]]:
        lab_ids = self.filters.lab_ids
        await self.cur.execute(
            f"""
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
            """,
            [lab_ids, self.root_structure_id, lab_ids, self.root_structure_id] + p,
        )
        r = await self.cur.fetchone()
        await self.cur.execute(
            "SELECT COALESCE(acronym, name) AS label FROM structures WHERE id = %s",
            (lab_ids[0],),
        )
        row = await self.cur.fetchone()
        lab_label = row["label"] if row else "ce labo"
        return [
            {"value": "this_lab", "text": f"APC — {lab_label}", "count": r["apc_this_lab"]},
            {"value": "other_uca", "text": "APC — autres UCA", "count": r["apc_other_uca"]},
            {"value": "non_uca", "text": "APC hors UCA", "count": r["apc_non_uca"]},
            {"value": "none", "text": "Sans APC", "count": r["apc_none"]},
        ]

    async def _facet_apc_without_lab(self, where: str, p: list[Any]) -> list[dict[str, Any]]:
        await self.cur.execute(
            f"""
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
            """,
            [self.root_structure_id, self.root_structure_id] + p,
        )
        r = await self.cur.fetchone()
        return [
            {"value": "uca", "text": "APC — UCA", "count": r["apc_uca"]},
            {"value": "other", "text": "APC — autres", "count": r["apc_other"]},
            {"value": "none", "text": "Sans APC", "count": r["apc_none"]},
        ]

    async def _facet_countries(self) -> list[dict[str, Any]]:
        c, p = self._conds_skipping("country")
        await self.cur.execute(
            f"""
            SELECT co.code, co.name, COUNT(*) AS count
            FROM (
                SELECT unnest(p.countries) AS cc
                FROM publications p
                WHERE {self._where_sql(c)} AND p.countries IS NOT NULL
            ) sub
            JOIN countries co ON co.code = sub.cc
            GROUP BY co.code, co.name
            ORDER BY count DESC
            """,
            p,
        )
        return [
            {"value": r["code"].strip(), "text": r["name"], "count": r["count"]}
            for r in await self.cur.fetchall()
            if r["code"].strip() != "xx"
        ]

    async def _facet_hal_status(self) -> list[dict[str, Any]]:
        """HAL status : seulement si un seul labo est sélectionné."""
        if len(self.filters.lab_ids) != 1:
            return []
        c, p = self._conds_skipping("hal_status")
        col = self.lab_hal_col
        if col:
            await self.cur.execute(
                f"""
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
                          AND sd.hal_collections @> ARRAY[%s]
                    )) AS hors_collection,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                          AND sd.hal_collections @> ARRAY[%s]
                    ) AND (p.oa_status IS NULL OR p.oa_status::text IN {OA_CLOSED_SQL})
                    ) AS notice,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM source_publications sd
                        WHERE sd.publication_id = p.id AND sd.source = 'hal'
                          AND sd.hal_collections @> ARRAY[%s]
                    ) AND p.oa_status IS NOT NULL
                      AND p.oa_status::text NOT IN {OA_CLOSED_SQL}
                    ) AS ok
                FROM publications p
                WHERE {self._where_sql(c)}
                """,
                [col, col, col] + p,
            )
        else:
            await self.cur.execute(
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
                WHERE {self._where_sql(c)}
                """,
                p,
            )
        r = await self.cur.fetchone()
        return [
            {"value": "ok", "text": "OK", "count": r["ok"]},
            {"value": "notice", "text": "Notice", "count": r["notice"]},
            {"value": "hors_collection", "text": "Hors collection", "count": r["hors_collection"]},
            {"value": "hors_hal", "text": "Hors HAL", "count": r["hors_hal"]},
        ]

    async def _facet_in_perimeter(self) -> list[dict[str, Any]]:
        if not self.filters.person_id:
            return []
        c, p = self._conds_skipping("in_perimeter")
        await self.cur.execute(
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
            WHERE {self._where_sql(c)}
            """,
            [self.filters.person_id, self.filters.person_id] + p,
        )
        r = await self.cur.fetchone()
        return [
            {"value": "yes", "text": "UCA", "count": r["yes"]},
            {"value": "no", "text": "Hors périmètre", "count": r["no"]},
        ]


async def publications_facets(
    cur: Any, *, filters: FacetFilters, root_structure_id: int
) -> dict[str, Any]:
    """Facettes dynamiques : chaque facette exclut son propre filtre mais
    applique tous les autres.

    Les facettes sont indépendantes — on les calcule en parallèle, chacune
    sur sa propre connexion du pool. Le `cur` passé en argument sert
    uniquement au préchargement de `lab_hal_col` (lookup unique).
    """
    # Préchargement (1 query, sur la conn courante)
    preload = _PublicationFacetsBuilder(cur, filters, root_structure_id)
    await preload._preload_lab_hal_col()
    lab_hal_col = preload.lab_hal_col

    pool = get_async_pool()

    async def run(facet: Callable[[_PublicationFacetsBuilder], Awaitable[Any]]) -> Any:
        async with pool.connection() as conn, conn.cursor() as new_cur:
            await new_cur.execute("SET LOCAL jit = off")
            b = _PublicationFacetsBuilder(new_cur, filters, root_structure_id)
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
