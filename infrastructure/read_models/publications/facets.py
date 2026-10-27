"""Facettes dynamiques pour /api/publications/facets.

Chaque facette exclut son propre filtre mais applique tous les autres. Les facettes sont indépendantes et s'exécutent en parallèle, chacune sur sa propre connexion (cf. `PublicationFacetQueries.publications_facets`).
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any

from sqlalchemy import Connection, text

from domain.countries import NO_COUNTRY_CODE
from domain.publications.licenses import license_label
from domain.publications.metadata import OaStatus
from domain.sources.hal import HAL_DEPOSIT_STATUS_LABELS, HAL_DEPOSIT_STATUSES
from domain.structures.structure import StructureType
from infrastructure.db.rows import rows_as
from infrastructure.read_models._common import (
    EntityFacetResponse,
    EntityKind,
    FacetOption,
    YesNoCount,
)
from infrastructure.read_models.entity_facet import entity_facet_rows
from infrastructure.read_models.filters import (
    OA_CLOSED_SQL,
    OA_OPEN_SQL,
    hal_status_expression,
    institution_apc_payment_sql,
    own_structure_ids,
)
from infrastructure.read_models.perimeters.queries import get_persons_perimeter_name
from infrastructure.read_models.publications.filtering import (
    FilterContext,
    FilterDimension,
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import (
    NO_LICENSE,
    PublicationFilters,
    PublicationsFacetsResponse,
)


class _PublicationFacetsBuilder:
    """Construit les facettes dynamiques pour /api/publications/facets : une méthode privée `_facet_*` par facette, orchestrées par `PublicationFacetQueries.publications_facets`.

    Chaque facette exclut son propre filtre mais applique tous les autres.
    """

    def __init__(
        self, conn: Connection, filters: PublicationFilters, context: FilterContext
    ) -> None:
        self.conn = conn
        self.filters = filters
        self.context = context

    def _clauses_skipping(self, skip: FilterDimension) -> tuple[str, dict[str, object]]:
        """WHERE sous tous les filtres sauf celui de `skip`."""
        return publication_filter_where(self.filters, self.context, skip)

    # ── Facettes ────────────────────────────────────────────────

    def _facet_years(self) -> list[FacetOption]:
        where_sql, binds = self._clauses_skipping("year")
        rows = self.conn.execute(
            text(f"""
                SELECT p.publication_year::text AS value, COUNT(*) AS count
                FROM publications p
                WHERE {where_sql} AND p.publication_year IS NOT NULL
                GROUP BY p.publication_year ORDER BY p.publication_year DESC
            """),
            binds,
        )
        return rows_as(FacetOption, rows)

    def _facet_labs(self) -> tuple[list[FacetOption], int]:
        where_sql, binds = self._clauses_skipping("lab")
        # `publication_structures` (matview publi↔structure dédoublonnée) → COUNT(*) par structure, sans jointure contributions ni DISTINCT/tri (cf. migration d8b3f5a2c9e6). `where_sql` ne porte que sur `p` (publications).
        labs_rows = self.conn.execute(
            text(f"""
                SELECT s.id::text AS value, COALESCE(s.acronym, s.name) AS label,
                       COUNT(*) AS count
                FROM publication_structures ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN structures s ON s.id = ps.structure_id
                WHERE {where_sql}
                  AND s.structure_type = '{StructureType.LABO.value}'
                GROUP BY s.id, s.acronym, s.name
                ORDER BY count DESC
            """),
            binds,
        )
        labs = rows_as(FacetOption, labs_rows)

        no_lab_row = self.conn.execute(
            text(f"""
                SELECT COUNT(*) AS total FROM publications p
                WHERE {where_sql}
                  AND NOT EXISTS (
                      SELECT 1 FROM publication_structures ps
                      JOIN structures s ON s.id = ps.structure_id
                      WHERE ps.publication_id = p.id
                        AND s.structure_type = '{StructureType.LABO.value}'
                  )
            """),
            binds,
        ).one()
        return labs, no_lab_row.total

    def _facet_doc_types(self) -> list[FacetOption]:
        where_sql, binds = self._clauses_skipping("doc_type")
        rows = self.conn.execute(
            text(f"""
                SELECT p.doc_type::text AS value, COUNT(*) AS count
                FROM publications p
                WHERE {where_sql} AND p.doc_type IS NOT NULL
                GROUP BY p.doc_type ORDER BY count DESC
            """),
            binds,
        )
        return rows_as(FacetOption, rows)

    def _facet_licenses(self) -> list[FacetOption]:
        """Licence de la version éditeur, `NO_LICENSE` pour les publications sans licence connue."""
        where_sql, binds = self._clauses_skipping("license")
        rows = self.conn.execute(
            text(f"""
                SELECT COALESCE(p.license::text, '{NO_LICENSE}') AS value, COUNT(*) AS n
                FROM publications p
                WHERE {where_sql}
                GROUP BY 1 ORDER BY n DESC
            """),
            binds,
        )
        return [
            FacetOption(
                value=r.value,
                label=license_label(None if r.value == NO_LICENSE else r.value),
                count=r.n,
            )
            for r in rows
        ]

    def _facet_access(self) -> list[FacetOption]:
        where_sql, binds = self._clauses_skipping("access")
        r = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE p.oa_status::text IN {OA_OPEN_SQL}) AS open_count,
                    COUNT(*) FILTER (WHERE p.oa_status::text = '{OaStatus.EMBARGOED.value}') AS embargo_count,
                    COUNT(*) FILTER (
                        WHERE p.oa_status::text IN {OA_CLOSED_SQL}
                           OR p.oa_status IS NULL
                    ) AS closed_count
                FROM publications p
                WHERE {where_sql}
            """),
            binds,
        ).one()
        return [
            FacetOption(value="open", label="Ouvert", count=r.open_count),
            FacetOption(value="embargo", label="Sous embargo", count=r.embargo_count),
            FacetOption(value="closed", label="Fermé", count=r.closed_count),
        ]

    def _facet_oa_statuses(self) -> list[FacetOption]:
        where_sql, binds = self._clauses_skipping("oa_status")
        rows = self.conn.execute(
            text(f"""
                SELECT p.oa_status::text AS value, COUNT(*) AS count
                FROM publications p
                WHERE {where_sql} AND p.oa_status IS NOT NULL
                GROUP BY p.oa_status ORDER BY count DESC
            """),
            binds,
        )
        return rows_as(FacetOption, rows)

    def _facet_corresponding(self) -> list[FacetOption]:
        if not self.filters.person_id:
            return []
        where_sql, binds = self._clauses_skipping("corresponding")
        row = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM contributions a
                        WHERE a.publication_id = p.id AND a.person_id = :corr_pid
                          AND a.is_corresponding = TRUE
                    )) AS yes_count,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM contributions a
                        WHERE a.publication_id = p.id AND a.person_id = :corr_pid
                          AND a.is_corresponding = TRUE
                    )) AS no_count
                FROM publications p
                WHERE {where_sql}
            """),
            {**binds, "corr_pid": self.filters.person_id},
        ).one()
        return [
            FacetOption(value="yes", count=row.yes_count),
            FacetOption(value="no", count=row.no_count),
        ]

    def _facet_source_counts(self) -> dict[str, YesNoCount]:
        """Counts {yes, no} par source, ignorant en bloc tous les filtres source."""
        where_sql, binds = self._clauses_skipping("source")
        row = self.conn.execute(
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
        ).one()
        return {
            "hal": YesNoCount(yes=row.hal_yes, no=row.hal_no),
            "oa": YesNoCount(yes=row.oa_yes, no=row.oa_no),
            "scanr": YesNoCount(yes=row.scanr_yes, no=row.scanr_no),
            "wos": YesNoCount(yes=row.wos_yes, no=row.wos_no),
            "theses": YesNoCount(yes=row.theses_yes, no=row.theses_no),
        }

    def _facet_apc(self) -> list[FacetOption]:
        """APC payées par le périmètre : oui ou non."""
        where, binds = self._clauses_skipping("apc")
        paid = institution_apc_payment_sql("apc_facet_root_ids")
        r = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE {paid}) AS apc_yes,
                    COUNT(*) FILTER (WHERE NOT {paid}) AS apc_no
                FROM publications p
                WHERE {where}
            """),
            {**binds, "apc_facet_root_ids": self.context.perimeter_structure_ids},
        ).one()
        return [
            FacetOption(
                value="yes",
                label=f"APC — {get_persons_perimeter_name(self.conn)}",
                count=r.apc_yes,
            ),
            FacetOption(value="no", label="Sans APC", count=r.apc_no),
        ]

    def _facet_countries(self) -> list[FacetOption]:
        where_sql, binds = self._clauses_skipping("country")
        rows = self.conn.execute(
            text(f"""
                SELECT co.code, co.name, COUNT(*) AS n
                FROM (
                    SELECT unnest(p.countries) AS cc
                    FROM publications p
                    WHERE {where_sql} AND p.countries IS NOT NULL
                ) sub
                JOIN countries co ON co.code = sub.cc
                GROUP BY co.code, co.name
                ORDER BY n DESC
            """),
            binds,
        ).all()
        return [
            FacetOption(value=r.code.strip(), label=r.name, count=r.n)
            for r in rows
            if r.code.strip() != NO_COUNTRY_CODE
        ]

    def _facet_languages(self) -> list[FacetOption]:
        where_sql, binds = self._clauses_skipping("language")
        rows = self.conn.execute(
            text(f"""
                SELECT l.code, l.name, COUNT(*) AS n
                FROM publications p
                JOIN languages l ON l.code = p.language
                WHERE {where_sql}
                GROUP BY l.code, l.name
                ORDER BY n DESC
            """),
            binds,
        ).all()
        return [FacetOption(value=r.code, label=r.name, count=r.n) for r in rows]

    def _facet_hal_status(self) -> list[FacetOption]:
        """HAL status : seulement si un seul labo est sélectionné."""
        if len(self.filters.lab_ids) != 1:
            return []
        where_sql, binds = self._clauses_skipping("hal_status")
        status = hal_status_expression(self.context.lab_hal_collection)
        rows = self.conn.execute(
            text(f"""
                SELECT value, COUNT(*) AS n
                FROM (SELECT {status.sql} AS value FROM publications p WHERE {where_sql}) s
                GROUP BY value
            """),
            {**binds, **status.binds},
        ).all()
        counts = {r.value: r.n for r in rows}
        return [
            FacetOption(value=s, label=HAL_DEPOSIT_STATUS_LABELS[s], count=counts.get(s, 0))
            for s in HAL_DEPOSIT_STATUSES
        ]

    def _facet_in_perimeter(self) -> list[FacetOption]:
        if not self.filters.person_id:
            return []
        where_sql, binds = self._clauses_skipping("in_perimeter")
        r = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM contributions a
                        WHERE a.publication_id = p.id AND a.person_id = :inp_pid
                          AND a.in_perimeter = TRUE
                    )) AS yes,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM contributions a
                        WHERE a.publication_id = p.id AND a.person_id = :inp_pid
                          AND a.in_perimeter = TRUE
                    )) AS no
                FROM publications p
                WHERE {where_sql}
            """),
            {**binds, "inp_pid": self.filters.person_id},
        ).one()
        return [
            FacetOption(value="yes", label=get_persons_perimeter_name(self.conn), count=r.yes),
            FacetOption(value="no", label="Hors périmètre", count=r.no),
        ]


_ENTITY_FACET_LIMIT = 20


class PublicationFacetQueries:
    _conn: Connection
    _open_connection: Callable[[], Connection]

    def publications_facets(self, *, filters: PublicationFilters) -> PublicationsFacetsResponse:
        """Facettes dynamiques : chaque facette exclut son propre filtre mais applique tous les autres.

        Les ~11 facettes sont **indépendantes** et chacune est un agrégat sur l'ensemble filtré (~0,5 s). On les exécute en **parallèle**, chacune dans un thread avec sa propre connexion ouverte par `_open_connection` (psycopg libère le GIL pendant la requête). Le contexte de filtrage est lu une fois et partagé.
        """
        context = filter_context(self._conn, filters)

        def run(method_name: str) -> Any:
            with self._open_connection() as facet_conn:
                facet_conn.execute(text("SET LOCAL jit = off"))
                builder = _PublicationFacetsBuilder(facet_conn, filters, context)
                return getattr(builder, method_name)()

        facet_methods = {
            "years": "_facet_years",
            "labs": "_facet_labs",
            "doc_types": "_facet_doc_types",
            "access": "_facet_access",
            "oa_statuses": "_facet_oa_statuses",
            "licenses": "_facet_licenses",
            "corresponding": "_facet_corresponding",
            "source_counts": "_facet_source_counts",
            "apc": "_facet_apc",
            "countries": "_facet_countries",
            "languages": "_facet_languages",
            "hal_status": "_facet_hal_status",
            "in_perimeter": "_facet_in_perimeter",
        }
        # Chaque tâche entre dans sa propre copie du contexte de la requête, qui contient la déclaration de lecture.
        with ThreadPoolExecutor(max_workers=len(facet_methods)) as pool:
            futures = {
                key: pool.submit(copy_context().run, run, name)
                for key, name in facet_methods.items()
            }
            results = {key: future.result() for key, future in futures.items()}

        labs, no_lab_count = results.pop("labs")
        return PublicationsFacetsResponse(
            years=results["years"],
            labs=labs,
            no_lab_count=no_lab_count,
            doc_types=results["doc_types"],
            access=results["access"],
            oa_statuses=results["oa_statuses"],
            licenses=results["licenses"],
            corresponding=results["corresponding"],
            source_counts=results["source_counts"],
            apc=results["apc"],
            countries=results["countries"],
            languages=results["languages"],
            hal_status=results["hal_status"],
            in_perimeter=results["in_perimeter"],
        )

    def publications_entity_facet(
        self,
        *,
        kind: EntityKind,
        search: str,
        filters: PublicationFilters,
    ) -> EntityFacetResponse:
        """Facette éditeur, revue, auteur ou sujet contextuelle de la liste : N premières entités sous les filtres actifs, en sautant le filtre de la dimension demandée (les autres, dont l'autre entité, restent appliqués → corrélation). Recherche serveur par nom."""
        context = filter_context(self._conn, filters)
        where_sql, binds = publication_filter_where(filters, context, kind)
        return EntityFacetResponse(
            entities=entity_facet_rows(
                self._conn,
                kind=kind,
                where_sql=where_sql,
                binds=binds,
                search=search,
                limit=_ENTITY_FACET_LIMIT,
                own_structure_ids=own_structure_ids(
                    filters.lab_ids, context.perimeter_structure_ids
                ),
            )
        )
