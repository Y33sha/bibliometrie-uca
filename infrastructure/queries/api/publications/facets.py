"""Facettes dynamiques pour /api/publications/facets.

Chaque facette exclut son propre filtre mais applique tous les autres. Les facettes sont indépendantes et s'exécutent en parallèle, chacune sur sa propre connexion (cf. `publications_facets`).
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.publications_queries import PublicationFilters
from domain.countries import NO_COUNTRY_CODE
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.api.filters import (
    OA_CLOSED_SQL,
    OA_OPEN_SQL,
    PUBLICATION_IS_IN_PERIMETER,
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
    search_clause,
    source_clause,
    subject_clause,
    year_clause,
)


class _PublicationFacetsBuilder:
    """Construit les facettes dynamiques pour /api/publications/facets : une méthode privée `_facet_*` par facette, orchestrées par la fonction `publications_facets`.

    Chaque facette exclut son propre filtre mais applique tous les autres.
    """

    def __init__(
        self, conn: Connection, filters: PublicationFilters, perimeter_structure_ids: list[int]
    ) -> None:
        self.conn = conn
        self.filters = filters
        self.perimeter_structure_ids = perimeter_structure_ids
        self.lab_hal_col: str | None = None

    # ── Utilitaires internes ────────────────────────────────────

    def _preload_lab_hal_col(self) -> None:
        """Charge la hal_collection du labo (si un seul labo est sélectionné)."""
        if len(self.filters.lab_ids) == 1:
            row = self.conn.execute(
                text("SELECT hal_collection FROM structures WHERE id = :sid"),
                {"sid": self.filters.lab_ids[0]},
            ).one_or_none()
            self.lab_hal_col = row.hal_collection if row else None

    def _base_clauses(self) -> list[WhereClause | None]:
        """Conditions de base : publications UCA ou par personne."""
        f = self.filters
        out: list[WhereClause | None] = []
        if f.person_id:
            out.append(person_clause(f.person_id))
        else:
            out.append(WhereClause(PUBLICATION_IS_IN_PERIMETER, {}))
        out.append(excluded_doc_type_clause(f.excluded_types))
        # Recherche titre/sujet : filtre global (jamais une dimension de facette), appliqué à tous les comptes pour qu'ils suivent le champ de recherche.
        out.append(search_clause(f.search))
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
            clauses.append(apc_clause(f.has_apc, self.perimeter_structure_ids, f.lab_ids))
        if skip != "publisher":
            clauses.append(publisher_id_clause(f.publisher_id))
        if skip != "journal":
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

    def _facet_years(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("year")
        rows = self.conn.execute(
            text(f"""
                SELECT p.pub_year::text AS value, COUNT(*) AS count
                FROM publications p
                WHERE {where_sql} AND p.pub_year IS NOT NULL
                GROUP BY p.pub_year ORDER BY p.pub_year DESC
            """),
            binds,
        ).all()
        return [dict(r._mapping) for r in rows]

    def _facet_labs(self) -> tuple[list[dict[str, Any]], int]:
        where_sql, binds = self._clauses_skipping("lab")
        # `publication_structures` (matview publi↔structure dédoublonnée) → COUNT(*) par structure, sans jointure authorships ni DISTINCT/tri (cf. migration d8b3f5a2c9e6). `where_sql` ne porte que sur `p` (publications).
        labs_rows = self.conn.execute(
            text(f"""
                SELECT s.id::text AS value, COALESCE(s.acronym, s.name) AS label,
                       COUNT(*) AS count
                FROM publication_structures ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN structures s ON s.id = ps.structure_id
                WHERE {where_sql}
                  AND s.structure_type = 'labo'
                GROUP BY s.id, s.acronym, s.name
                ORDER BY count DESC
            """),
            binds,
        ).all()
        labs = [dict(r._mapping) for r in labs_rows]

        no_lab_row = self.conn.execute(
            text(f"""
                SELECT COUNT(*) AS total FROM publications p
                WHERE {where_sql}
                  AND NOT EXISTS (
                      SELECT 1 FROM publication_structures ps
                      JOIN structures s ON s.id = ps.structure_id
                      WHERE ps.publication_id = p.id
                        AND s.structure_type = 'labo'
                  )
            """),
            binds,
        ).one()
        return labs, no_lab_row.total

    def _facet_doc_types(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("doc_type")
        rows = self.conn.execute(
            text(f"""
                SELECT p.doc_type::text AS value, COUNT(*) AS count
                FROM publications p
                WHERE {where_sql} AND p.doc_type IS NOT NULL
                GROUP BY p.doc_type ORDER BY count DESC
            """),
            binds,
        ).all()
        return [dict(r._mapping) for r in rows]

    def _facet_access(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("access")
        r = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE p.oa_status::text IN {OA_OPEN_SQL}) AS open_count,
                    COUNT(*) FILTER (WHERE p.oa_status::text = 'embargoed') AS embargo_count,
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
            {"value": "open", "label": "Ouvert", "count": r.open_count},
            {"value": "embargo", "label": "Sous embargo", "count": r.embargo_count},
            {"value": "closed", "label": "Fermé", "count": r.closed_count},
        ]

    def _facet_oa_statuses(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("oa_status")
        rows = self.conn.execute(
            text(f"""
                SELECT p.oa_status::text AS value, COUNT(*) AS count
                FROM publications p
                WHERE {where_sql} AND p.oa_status IS NOT NULL
                GROUP BY p.oa_status ORDER BY count DESC
            """),
            binds,
        ).all()
        return [dict(r._mapping) for r in rows]

    def _facet_corresponding(self) -> list[dict[str, Any]]:
        if not self.filters.person_id:
            return []
        where_sql, binds = self._clauses_skipping("corresponding")
        row = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = :corr_pid
                          AND a.is_corresponding = TRUE
                    )) AS yes_count,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = :corr_pid
                          AND a.is_corresponding = TRUE
                    )) AS no_count
                FROM publications p
                WHERE {where_sql}
            """),
            {**binds, "corr_pid": self.filters.person_id},
        ).one()
        return [
            {"value": "yes", "count": row.yes_count},
            {"value": "no", "count": row.no_count},
        ]

    def _facet_source_counts(self) -> dict[str, dict[str, int]]:
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
            "hal": {"yes": row.hal_yes, "no": row.hal_no},
            "oa": {"yes": row.oa_yes, "no": row.oa_no},
            "scanr": {"yes": row.scanr_yes, "no": row.scanr_no},
            "wos": {"yes": row.wos_yes, "no": row.wos_no},
            "theses": {"yes": row.theses_yes, "no": row.theses_no},
        }

    def _facet_apc(self) -> list[dict[str, Any]]:
        """APC : variante à 4 catégories si un labo est sélectionné, sinon 3."""
        where_sql, binds = self._clauses_skipping("apc")
        if self.filters.lab_ids:
            return self._facet_apc_with_lab(where_sql, binds)
        return self._facet_apc_without_lab(where_sql, binds)

    def _facet_apc_with_lab(self, where: str, binds: dict[str, Any]) -> list[dict[str, Any]]:
        lab_ids = self.filters.lab_ids
        r = self.conn.execute(
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
                          AND ap.budget_structure_id = ANY(CAST(:apc_facet_root_ids AS int[]))
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
                          AND ap.budget_structure_id = ANY(CAST(:apc_facet_root_ids AS int[]))
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
                "apc_facet_root_ids": self.perimeter_structure_ids,
            },
        ).one()
        label_row = self.conn.execute(
            text("SELECT COALESCE(acronym, name) AS label FROM structures WHERE id = :id"),
            {"id": lab_ids[0]},
        ).one_or_none()
        lab_label = label_row.label if label_row else "ce labo"
        return [
            {"value": "this_lab", "label": f"APC — {lab_label}", "count": r.apc_this_lab},
            {"value": "other_uca", "label": "APC — autres UCA", "count": r.apc_other_uca},
            {"value": "non_uca", "label": "APC hors UCA", "count": r.apc_non_uca},
            {"value": "none", "label": "Sans APC", "count": r.apc_none},
        ]

    def _facet_apc_without_lab(self, where: str, binds: dict[str, Any]) -> list[dict[str, Any]]:
        r = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id
                          AND ap.budget_structure_id = ANY(CAST(:apc_facet_root_ids AS int[]))
                    )) AS apc_uca,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                    ) AND NOT EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id
                          AND ap.budget_structure_id = ANY(CAST(:apc_facet_root_ids AS int[]))
                    )) AS apc_other,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                    )) AS apc_none
                FROM publications p
                WHERE {where}
            """),
            {**binds, "apc_facet_root_ids": self.perimeter_structure_ids},
        ).one()
        return [
            {"value": "uca", "label": "APC — UCA", "count": r.apc_uca},
            {"value": "other", "label": "APC — autres", "count": r.apc_other},
            {"value": "none", "label": "Sans APC", "count": r.apc_none},
        ]

    def _facet_countries(self) -> list[dict[str, Any]]:
        where_sql, binds = self._clauses_skipping("country")
        rows = self.conn.execute(
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
        ).all()
        return [
            {"value": r.code.strip(), "label": r.name, "count": r.count}
            for r in rows
            if r.code.strip() != NO_COUNTRY_CODE
        ]

    def _facet_hal_status(self) -> list[dict[str, Any]]:
        """HAL status : seulement si un seul labo est sélectionné."""
        if len(self.filters.lab_ids) != 1:
            return []
        where_sql, binds = self._clauses_skipping("hal_status")
        col = self.lab_hal_col
        if col:
            r = self.conn.execute(
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
            ).one()
        else:
            r = self.conn.execute(
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
            ).one()
        return [
            {"value": "ok", "label": "OK", "count": r.ok},
            {"value": "notice", "label": "Notice", "count": r.notice},
            {"value": "hors_collection", "label": "Hors collection", "count": r.hors_collection},
            {"value": "hors_hal", "label": "Hors HAL", "count": r.hors_hal},
        ]

    def _facet_in_perimeter(self) -> list[dict[str, Any]]:
        if not self.filters.person_id:
            return []
        where_sql, binds = self._clauses_skipping("in_perimeter")
        r = self.conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = :inp_pid
                          AND a.in_perimeter = TRUE
                    )) AS yes,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = :inp_pid
                          AND a.in_perimeter = TRUE
                    )) AS no
                FROM publications p
                WHERE {where_sql}
            """),
            {**binds, "inp_pid": self.filters.person_id},
        ).one()
        return [
            {"value": "yes", "label": "UCA", "count": r.yes},
            {"value": "no", "label": "Hors périmètre", "count": r.no},
        ]


def publications_facets(
    conn: Connection, *, filters: PublicationFilters, perimeter_structure_ids: list[int]
) -> dict[str, Any]:
    """Facettes dynamiques : chaque facette exclut son propre filtre mais applique tous les autres.

    Les ~11 facettes sont **indépendantes** et chacune est un agrégat sur l'ensemble filtré (~0,5 s). On les exécute en **parallèle**, chacune dans un thread avec sa propre connexion (psycopg libère le GIL pendant la requête). Le `lab_hal_col` est préchargé une fois et partagé (lecture seule).
    """
    pre = _PublicationFacetsBuilder(conn, filters, perimeter_structure_ids)
    pre._preload_lab_hal_col()
    lab_hal_col = pre.lab_hal_col
    engine = get_sync_engine()

    def run(method_name: str) -> Any:
        with engine.connect() as facet_conn:
            facet_conn.execute(text("SET LOCAL jit = off"))
            builder = _PublicationFacetsBuilder(facet_conn, filters, perimeter_structure_ids)
            builder.lab_hal_col = lab_hal_col
            return getattr(builder, method_name)()

    facet_methods = {
        "years": "_facet_years",
        "labs": "_facet_labs",
        "doc_types": "_facet_doc_types",
        "access": "_facet_access",
        "oa_statuses": "_facet_oa_statuses",
        "corresponding": "_facet_corresponding",
        "source_counts": "_facet_source_counts",
        "apc": "_facet_apc",
        "countries": "_facet_countries",
        "hal_status": "_facet_hal_status",
        "in_perimeter": "_facet_in_perimeter",
    }
    with ThreadPoolExecutor(max_workers=len(facet_methods)) as pool:
        futures = {key: pool.submit(run, name) for key, name in facet_methods.items()}
        results = {key: future.result() for key, future in futures.items()}

    labs, no_lab_count = results.pop("labs")
    return {"labs": labs, "no_lab_count": no_lab_count, **results}


# Liaison SQL des facettes-entités à forte cardinalité (recherche serveur). La revue sort directement de `publications.journal_id` ; l'éditeur passe par une jointure un-à-un vers `publishers` (qui exclut les publications sans éditeur).
_ENTITY_SQL: dict[str, dict[str, str]] = {
    "journal": {"id": "j.id", "label": "j.title", "join": ""},
    "publisher": {
        "id": "pub.id",
        "label": "pub.name",
        "join": "JOIN publishers pub ON pub.id = j.publisher_id",
    },
}


def publications_entity_facet(
    conn: Connection,
    *,
    kind: str,
    search: str,
    filters: PublicationFilters,
    perimeter_structure_ids: list[int],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Facette éditeur/revue contextuelle de la liste : N premières entités sous les filtres actifs,
    en sautant le filtre de la dimension demandée (les autres, dont l'autre entité, restent
    appliqués → corrélation). Décompte par `COUNT(*)` (filtres scalaires ou `EXISTS`, sans
    démultiplication). Recherche serveur par nom."""
    builder = _PublicationFacetsBuilder(conn, filters, perimeter_structure_ids)
    builder._preload_lab_hal_col()
    where_sql, binds = builder._clauses_skipping(kind)

    sp = _ENTITY_SQL[kind]
    name_filter = ""
    if len(search.strip()) >= 2:
        name_filter = f" AND unaccent({sp['label']}) ILIKE unaccent(:q)"
        binds["q"] = f"%{search.strip()}%"
    binds["lim"] = limit

    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(
        text(f"""
            SELECT {sp["id"]} AS id, {sp["label"]} AS label, COUNT(*) AS count
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id {sp["join"]}
            WHERE {where_sql} AND {sp["id"]} IS NOT NULL{name_filter}
            GROUP BY {sp["id"]}, {sp["label"]}
            ORDER BY count DESC, label
            LIMIT :lim
        """),
        binds,
    ).all()
    return [{"id": r.id, "label": r.label, "count": r.count} for r in rows]
