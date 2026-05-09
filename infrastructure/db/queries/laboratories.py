"""Query services pour /api/laboratories/*.

Implémente le port `application.ports.laboratories_queries.LaboratoriesQueries`
via `PgLaboratoriesQueries` (constructor injection de la `Connection`
SA). Conformité au port assurée par duck typing : pas d'import du
Protocol depuis `infrastructure/` (règle DDD `infrastructure ⊥
application`). La dataclass `LabPersonsFilters` vit dans
`application/ports/` ; ici on type `filters: Any` puis on lit ses
attributs.
"""

import datetime
from typing import Any

from sqlalchemy import Connection, text

from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from infrastructure.db.queries.filters import (
    OA_CLOSED_SQL,
    WhereClause,
    assemble_where,
    person_has_identifier_clause,
    person_has_rh_clause,
    persons_sort_clause,
)
from infrastructure.perimeter import (
    get_persons_perimeter_root_ids,
    get_persons_structure_ids_list,
)

# Filtre étendu pour les stats de contribution effective d'un labo :
# OUT_OF_SCOPE (peer_review, memoir) + ongoing_thesis (les thèses en
# cours ne comptent pas comme contribution finalisée).
_DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS = sorted(OUT_OF_SCOPE_DOC_TYPES | {"ongoing_thesis"})
_DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS_SQL = (
    "(" + ", ".join(f"'{t}'" for t in _DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS) + ")"
)


class PgLaboratoriesQueries:
    """Adapter SA pour `application.ports.laboratories_queries.LaboratoriesQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_laboratories(self) -> list[dict[str, Any]]:
        """Liste des labos du périmètre, avec leurs tutelles (hors racines du périmètre).

        Résout en interne le périmètre `persons` (ids des structures + racines)
        avant de filtrer.
        """
        perimeter_ids = get_persons_structure_ids_list(self._conn)
        root_ids = get_persons_perimeter_root_ids(self._conn)
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.code, s.name, s.acronym,
                       s.ror_id, s.hal_collection,
                       (SELECT json_agg(json_build_object(
                           'id', sp.id, 'name', sp.name, 'acronym', sp.acronym,
                           'type', sp.structure_type::text
                       ) ORDER BY sp.name)
                        FROM structure_relations sr
                        JOIN structures sp ON sp.id = sr.parent_id
                        WHERE sr.child_id = s.id
                          AND sr.relation_type = 'est_tutelle_de'
                          AND NOT (sp.id = ANY(:root_ids))
                       ) AS tutelles
                FROM structures s
                WHERE s.structure_type = 'labo'
                  AND s.id = ANY(:perimeter_ids)
                ORDER BY s.name
            """),
            {"root_ids": root_ids, "perimeter_ids": perimeter_ids},
        ).all()
        return [dict(r._mapping) for r in rows]

    def get_laboratory(self, lab_id: int) -> dict[str, Any] | None:
        """Profil public d'un laboratoire (None si absent)."""
        struct_row = self._conn.execute(
            text("""
                SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type,
                       s.ror_id, s.rnsr_id, s.hal_collection
                FROM structures s
                WHERE s.id = :lab_id
            """),
            {"lab_id": lab_id},
        ).one_or_none()
        if not struct_row:
            return None

        parents = self._conn.execute(
            text("""
                SELECT sp.id, sp.name, sp.acronym, sp.structure_type::text AS type,
                       sr.relation_type
                FROM structure_relations sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = :lab_id
                ORDER BY sr.relation_type, sp.name
            """),
            {"lab_id": lab_id},
        ).all()

        children = self._conn.execute(
            text("""
                SELECT sc.id, sc.name, sc.acronym, sc.structure_type::text AS type,
                       sr.relation_type
                FROM structure_relations sr
                JOIN structures sc ON sc.id = sr.child_id
                WHERE sr.parent_id = :lab_id
                ORDER BY sc.name
            """),
            {"lab_id": lab_id},
        ).all()

        theses_row = self._conn.execute(
            text("""
                SELECT COUNT(*) AS count
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE p.doc_type IN ('thesis', 'ongoing_thesis')
                  AND :lab_id = ANY(a.structure_ids)
                  AND a.roles && ARRAY['author']::text[]
            """),
            {"lab_id": lab_id},
        ).one()

        return {
            "structure": dict(struct_row._mapping),
            "parents": [dict(r._mapping) for r in parents],
            "children": [dict(r._mapping) for r in children],
            "theses_count": theses_row.count,
        }

    def get_laboratory_persons(  # noqa: C901 (4 facettes × similar conditions)
        self,
        lab_id: int,
        *,
        filters: Any,
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]:
        """Personnes liées à un labo + authorships orphelines + facettes."""
        offset = (page - 1) * per_page
        lab_arr = [lab_id]

        extra_where, extra_binds = assemble_where(_lab_persons_extra_clauses(filters))
        base_where = (
            "a.person_id IS NOT NULL "
            "AND a.structure_ids && CAST(:lab_arr AS int[]) "
            "AND a.roles && ARRAY['author']::text[]"
        )
        full_where = f"{base_where} AND {extra_where}"
        common_binds = {**extra_binds, "lab_arr": lab_arr}

        count_row = self._conn.execute(
            text(f"""
                SELECT COUNT(DISTINCT a.person_id) AS total
                FROM authorships a
                JOIN persons p ON p.id = a.person_id
                LEFT JOIN persons_rh prh ON prh.person_id = p.id
                WHERE {full_where}
            """),
            common_binds,
        ).one()
        total_persons = count_row.total

        order_clause = persons_sort_clause(sort)
        persons_rows = self._conn.execute(
            text(f"""
                SELECT p.id, p.last_name, p.first_name,
                       prh.role_title, prh.department_name,
                       (prh.id IS NOT NULL) AS has_rh,
                       COUNT(DISTINCT a.publication_id) AS pub_count,
                       (SELECT json_agg(json_build_object(
                            'value', pi.id_value, 'confirmed', (pi.status = 'confirmed')
                        ) ORDER BY pi.id_value)
                        FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'orcid'
                          AND pi.status != 'rejected'
                       ) AS orcids,
                       (SELECT json_agg(json_build_object(
                            'value', pi.id_value, 'confirmed', (pi.status = 'confirmed')
                        ) ORDER BY pi.id_value)
                        FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idhal'
                          AND pi.status != 'rejected'
                       ) AS idhals,
                       (SELECT json_agg(json_build_object(
                            'value', pi.id_value, 'confirmed', (pi.status = 'confirmed')
                        ) ORDER BY pi.id_value)
                        FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idref'
                          AND pi.status != 'rejected'
                       ) AS idrefs
                FROM authorships a
                JOIN persons p ON p.id = a.person_id
                LEFT JOIN persons_rh prh ON prh.person_id = p.id
                WHERE {full_where}
                GROUP BY p.id, p.last_name, p.first_name,
                         prh.id, prh.role_title, prh.department_name
                ORDER BY {order_clause}
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**common_binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        persons = [dict(r._mapping) for r in persons_rows]

        orphan_row = self._conn.execute(
            text("""
                SELECT COUNT(DISTINCT a.id) AS total
                FROM authorships a
                WHERE a.person_id IS NULL
                  AND a.structure_ids && CAST(:lab_arr AS int[])
                  AND a.roles && ARRAY['author']::text[]
            """),
            {"lab_arr": lab_arr},
        ).one()
        orphan_total = orphan_row.total

        # Facettes (chacune exclut son propre filtre). Reconstruction du WHERE
        # avec le `per` alias propre aux facettes au lieu de `p`.
        def facet_clauses(*, skip: str) -> tuple[str, dict[str, Any]]:
            parts: list[str] = []
            binds: dict[str, Any] = {"lab_arr": lab_arr}
            if skip != "search" and filters.search:
                parts.append(
                    "(unaccent(per.last_name) ILIKE unaccent(:fac_search_pat) "
                    "OR unaccent(per.first_name) ILIKE unaccent(:fac_search_pat))"
                )
                binds["fac_search_pat"] = f"%{filters.search}%"
            if skip != "departments" and filters.departments:
                parts.append("prh.department_name = ANY(:fac_departments)")
                binds["fac_departments"] = filters.departments
            if skip != "roles" and filters.roles:
                parts.append("prh.role_title = ANY(:fac_roles)")
                binds["fac_roles"] = filters.roles
            if skip != "has_rh":
                if filters.has_rh == "yes":
                    parts.append("prh.id IS NOT NULL")
                elif filters.has_rh == "no":
                    parts.append("prh.id IS NULL")
            if skip != "ids":
                for id_type, val in (
                    ("orcid", filters.has_orcid),
                    ("idhal", filters.has_idhal),
                    ("idref", filters.has_idref),
                ):
                    if val == "yes":
                        parts.append(
                            f"EXISTS (SELECT 1 FROM person_identifiers pi "
                            f"WHERE pi.person_id = per.id AND pi.id_type = '{id_type}' "
                            f"AND pi.status != 'rejected')"
                        )
                    elif val == "no":
                        parts.append(
                            f"NOT EXISTS (SELECT 1 FROM person_identifiers pi "
                            f"WHERE pi.person_id = per.id AND pi.id_type = '{id_type}' "
                            f"AND pi.status != 'rejected')"
                        )
            full = (
                "a.person_id IS NOT NULL "
                "AND a.structure_ids && CAST(:lab_arr AS int[]) "
                "AND a.roles && ARRAY['author']::text[]"
            )
            if parts:
                full += " AND " + " AND ".join(parts)
            return full, binds

        def run_yesno_facet(skip: str) -> Any:
            w, p = facet_clauses(skip=skip)
            return self._conn.execute(
                text(f"""
                    SELECT
                        COUNT(DISTINCT per.id) FILTER (WHERE prh.id IS NOT NULL) AS rh_yes,
                        COUNT(DISTINCT per.id) FILTER (WHERE prh.id IS NULL) AS rh_no,
                        COUNT(DISTINCT per.id) FILTER (WHERE EXISTS (
                            SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id
                            AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                        )) AS orcid_yes,
                        COUNT(DISTINCT per.id) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id
                            AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                        )) AS orcid_no,
                        COUNT(DISTINCT per.id) FILTER (WHERE EXISTS (
                            SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id
                            AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                        )) AS idhal_yes,
                        COUNT(DISTINCT per.id) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id
                            AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                        )) AS idhal_no,
                        COUNT(DISTINCT per.id) FILTER (WHERE EXISTS (
                            SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id
                            AND pi.id_type = 'idref' AND pi.status != 'rejected'
                        )) AS idref_yes,
                        COUNT(DISTINCT per.id) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id
                            AND pi.id_type = 'idref' AND pi.status != 'rejected'
                        )) AS idref_no
                    FROM authorships a
                    JOIN persons per ON per.id = a.person_id
                    LEFT JOIN persons_rh prh ON prh.person_id = per.id
                    WHERE {w}
                """),
                p,
            ).one()

        def run_value_facet(*, skip: str, column: str) -> list[dict[str, Any]]:
            w, p = facet_clauses(skip=skip)
            rows = self._conn.execute(
                text(f"""
                    SELECT prh.{column} AS value, COUNT(DISTINCT per.id) AS count
                    FROM authorships a
                    JOIN persons per ON per.id = a.person_id
                    LEFT JOIN persons_rh prh ON prh.person_id = per.id
                    WHERE {w} AND prh.{column} IS NOT NULL
                    GROUP BY prh.{column}
                    ORDER BY count DESC
                """),
                p,
            ).all()
            return [dict(r._mapping) for r in rows]

        facet_rh = run_yesno_facet("has_rh")
        facet_ids = run_yesno_facet("ids")
        facet_depts = run_value_facet(skip="departments", column="department_name")
        facet_roles = run_value_facet(skip="roles", column="role_title")

        return {
            "total_persons": total_persons,
            "page": page,
            "per_page": per_page,
            "pages": (total_persons + per_page - 1) // per_page or 1,
            "persons": persons,
            "orphan_authorships": {"total": orphan_total},
            "facets": {
                "departments": facet_depts,
                "roles": facet_roles,
                "rh": {"yes": facet_rh.rh_yes, "no": facet_rh.rh_no},
                "orcid": {"yes": facet_ids.orcid_yes, "no": facet_ids.orcid_no},
                "idhal": {"yes": facet_ids.idhal_yes, "no": facet_ids.idhal_no},
                "idref": {"yes": facet_ids.idref_yes, "no": facet_ids.idref_no},
            },
        }

    def get_laboratory_addresses(self, lab_id: int, *, page: int, per_page: int) -> dict[str, Any]:
        """Adresses liées à un laboratoire."""
        offset = (page - 1) * per_page
        count_row = self._conn.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM addresses a
                JOIN address_structures ast ON ast.address_id = a.id
                WHERE ast.structure_id = :lab_id
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
            """),
            {"lab_id": lab_id},
        ).one()
        total = count_row.total

        rows = self._conn.execute(
            text("""
                SELECT a.id, a.raw_text, ast.is_confirmed
                FROM addresses a
                JOIN address_structures ast ON ast.address_id = a.id
                WHERE ast.structure_id = :lab_id
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                ORDER BY a.raw_text
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"lab_id": lab_id, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "addresses": [dict(r._mapping) for r in rows],
        }

    def get_laboratory_subjects(self, lab_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
        """Top sujets des publications d'un labo, ordonnés par fréquence locale.

        Filtre `peer_review`, `memoir`, `ongoing_thesis` pour rester cohérent
        avec ce qui est affiché dans l'onglet "Publications" de la page labo, et
        exclut les sujets trop génériques (`subjects.usage_count` > 5000).
        """
        # EXISTS plutôt que JOIN authorships : chaque publi apparaît une fois,
        # plutôt que dupliquée par auteur du labo. Le COUNT(DISTINCT p.id) reste
        # nécessaire car publication_subjects peut avoir plusieurs rows par
        # (pub_id, subject_id) (sources différentes).
        rows = self._conn.execute(
            text(f"""
                SELECT s.id, s.label, s.ontologies, COUNT(DISTINCT p.id) AS count
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE p.doc_type NOT IN {_DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS_SQL}
                  AND s.usage_count <= 5000
                  AND EXISTS (
                      SELECT 1 FROM authorships a
                      WHERE a.publication_id = p.id
                        AND a.structure_ids && CAST(:lab_arr AS int[])
                        AND a.roles && ARRAY['author']::text[]
                        AND a.in_perimeter = TRUE
                  )
                GROUP BY s.id, s.label, s.ontologies
                ORDER BY count DESC, lower(s.label)
                LIMIT :lim
            """),
            {"lab_arr": [lab_id], "lim": limit},
        ).all()
        return [dict(r._mapping) for r in rows]

    def get_laboratory_dashboard(self, lab_id: int) -> dict[str, Any]:
        """Dashboard labo : publis/an, répartition OA, collab internationales, top pays."""
        lab_arr = [lab_id]
        current_year = datetime.date.today().year

        pubs_year_rows = self._conn.execute(
            text("""
                SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE a.in_perimeter = TRUE
                  AND a.structure_ids && CAST(:lab_arr AS int[])
                  AND a.roles && ARRAY['author']::text[]
                  AND p.pub_year IS NOT NULL
                  AND p.pub_year >= :min_year
                GROUP BY p.pub_year
                ORDER BY p.pub_year
            """),
            {"lab_arr": lab_arr, "min_year": current_year - 6},
        ).all()
        pubs_by_year = [{"year": r.pub_year, "count": r.count} for r in pubs_year_rows]

        oa = self._conn.execute(
            text(f"""
                SELECT
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.oa_status NOT IN {OA_CLOSED_SQL} AND p.oa_status IS NOT NULL
                    ) AS open_access,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.oa_status = 'unknown' OR p.oa_status IS NULL
                    ) AS unknown,
                    COUNT(DISTINCT p.id) AS total
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE a.in_perimeter = TRUE
                  AND a.structure_ids && CAST(:lab_arr AS int[])
                  AND a.roles && ARRAY['author']::text[]
            """),
            {"lab_arr": lab_arr},
        ).one()

        collab = self._conn.execute(
            text("""
                SELECT
                    COUNT(DISTINCT p.id) AS total_articles,
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.countries IS NOT NULL
                          AND EXISTS (SELECT 1 FROM unnest(p.countries) c WHERE c NOT IN ('fr', 'xx'))
                    ) AS international
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE a.in_perimeter = TRUE
                  AND a.structure_ids && CAST(:lab_arr AS int[])
                  AND a.roles && ARRAY['author']::text[]
                  AND p.doc_type = 'article'
            """),
            {"lab_arr": lab_arr},
        ).one()

        # EXISTS plutôt que JOIN authorships : évite la duplication de chaque
        # publi par auteur du labo (× ~1.2) avant l'unnest des pays (× ~27),
        # ce qui faisait déborder le sort sur disque.
        top_country_rows = self._conn.execute(
            text("""
                SELECT co.code, co.name, COUNT(*) AS count
                FROM (
                    SELECT p.id, unnest(p.countries) AS cc
                    FROM publications p
                    WHERE p.doc_type = 'article'
                      AND EXISTS (
                          SELECT 1 FROM authorships a
                          WHERE a.publication_id = p.id
                            AND a.in_perimeter = TRUE
                            AND a.structure_ids && CAST(:lab_arr AS int[])
                            AND a.roles && ARRAY['author']::text[]
                      )
                ) sub
                JOIN countries co ON co.code = sub.cc
                WHERE sub.cc NOT IN ('fr', 'xx')
                GROUP BY co.code, co.name
                ORDER BY count DESC
                LIMIT 5
            """),
            {"lab_arr": lab_arr},
        ).all()
        top_countries = [
            {"code": r.code.strip(), "name": r.name, "count": r.count} for r in top_country_rows
        ]

        return {
            "pubs_by_year": pubs_by_year,
            "oa": {
                "open_access": oa.open_access,
                "closed": oa.closed,
                "unknown": oa.unknown,
                "total": oa.total,
            },
            "collab": {
                "total_articles": collab.total_articles,
                "international": collab.international,
                "domestic": collab.total_articles - collab.international,
            },
            "top_countries": top_countries,
        }


def _lab_persons_extra_clauses(filters: Any) -> list[WhereClause | None]:
    """Filtres optionnels en plus de la base (lab_id + roles author)."""
    out: list[WhereClause | None] = []
    if filters.search:
        out.append(
            WhereClause(
                """(
                    unaccent(p.last_name) ILIKE unaccent(:lp_search_pat)
                    OR unaccent(p.first_name) ILIKE unaccent(:lp_search_pat)
                )""",
                {"lp_search_pat": f"%{filters.search}%"},
            )
        )
    if filters.departments:
        out.append(
            WhereClause(
                "prh.department_name = ANY(:lp_departments)",
                {"lp_departments": filters.departments},
            )
        )
    if filters.roles:
        out.append(WhereClause("prh.role_title = ANY(:lp_roles)", {"lp_roles": filters.roles}))
    out.append(person_has_rh_clause(filters.has_rh))
    out.append(person_has_identifier_clause("orcid", filters.has_orcid))
    out.append(person_has_identifier_clause("idhal", filters.has_idhal))
    out.append(person_has_identifier_clause("idref", filters.has_idref))
    return out
