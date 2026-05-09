"""Query services pour le tableau de bord admin de feedback détection d'adresses.

Implémente le port `application.ports.admin_feedback_queries.AdminFeedbackQueries`
via `PgAdminFeedbackQueries`. Conformité au Protocol par duck typing —
pas d'import depuis `application/` (règle DDD).
"""

from typing import Any

from sqlalchemy import Connection, text


class PgAdminFeedbackQueries:
    """Adapter SA pour `AdminFeedbackQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def feedback_structures(self, types: list[str]) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.code, s.name, s.acronym,
                       s.structure_type::text AS type
                FROM structures s
                WHERE s.structure_type::text = ANY(:types)
                ORDER BY s.name
            """),
            {"types": types},
        ).all()
        return [dict(r._mapping) for r in rows]

    def feedback_stats(self, structure_id: int) -> dict[str, Any]:
        row = self._conn.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE is_confirmed IS NOT NULL) AS total_reviewed,
                    COUNT(*) FILTER (
                        WHERE is_confirmed = TRUE AND matched_form_id IS NOT NULL
                    ) AS concordant_valid,
                    COUNT(*) FILTER (
                        WHERE is_confirmed = FALSE AND matched_form_id IS NULL
                    ) AS concordant_rejected,
                    COUNT(*) FILTER (
                        WHERE is_confirmed = TRUE AND matched_form_id IS NULL
                    ) AS false_negatives,
                    COUNT(*) FILTER (
                        WHERE is_confirmed = FALSE AND matched_form_id IS NOT NULL
                    ) AS false_positives,
                    COUNT(*) FILTER (
                        WHERE is_confirmed IS NULL AND matched_form_id IS NOT NULL
                    ) AS pending
                FROM address_structures
                WHERE structure_id = :sid
            """),
            {"sid": structure_id},
        ).one()
        return dict(row._mapping)

    def feedback_false_negatives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> dict[str, Any]:
        return self._feedback_paginated(
            structure_id=structure_id,
            page=page,
            per_page=per_page,
            search=search,
            kind_where="ast.is_confirmed = TRUE AND ast.matched_form_id IS NULL",
            with_matched_forms=False,
        )

    def feedback_false_positives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> dict[str, Any]:
        return self._feedback_paginated(
            structure_id=structure_id,
            page=page,
            per_page=per_page,
            search=search,
            kind_where="ast.is_confirmed = FALSE AND ast.matched_form_id IS NOT NULL",
            with_matched_forms=True,
        )

    def _feedback_paginated(
        self,
        *,
        structure_id: int,
        page: int,
        per_page: int,
        search: str,
        kind_where: str,
        with_matched_forms: bool,
    ) -> dict[str, Any]:
        offset = (page - 1) * per_page
        binds: dict[str, Any] = {"sid": structure_id, "pg_limit": per_page, "pg_offset": offset}
        parts = ["ast.structure_id = :sid", kind_where]
        if search:
            parts.append("unaccent(a.raw_text) ILIKE unaccent(:search)")
            binds["search"] = f"%{search}%"
        where = " AND ".join(parts)

        total_row = self._conn.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM address_structures ast
                JOIN addresses a ON a.id = ast.address_id
                WHERE {where}
            """),
            binds,
        ).one()
        total = total_row.total

        matched_forms_select = (
            ""
            if not with_matched_forms
            else """,
                (SELECT json_agg(json_build_object(
                    'form_id', nf.id,
                    'form_text', nf.form_text,
                    'requires_context_of', nf.requires_context_of,
                    'structure_name', COALESCE(s.acronym, s.name)
                ))
                FROM address_structures ast2
                JOIN structure_name_forms nf ON nf.id = ast2.matched_form_id
                JOIN structures s ON s.id = nf.structure_id
                WHERE ast2.address_id = a.id
                  AND ast2.structure_id = :sid
                  AND ast2.matched_form_id IS NOT NULL
                ) AS matched_forms"""
        )

        rows = self._conn.execute(
            text(f"""
                SELECT
                    a.id, a.raw_text, a.pub_count,
                    (SELECT json_agg(json_build_object(
                        'structure_id', s.id, 'acronym', s.acronym, 'name', s.name,
                        'is_detected', (ast2.matched_form_id IS NOT NULL),
                        'is_confirmed', ast2.is_confirmed
                    ))
                    FROM address_structures ast2
                    JOIN structures s ON s.id = ast2.structure_id
                    WHERE ast2.address_id = a.id AND s.structure_type != 'site'
                    ) AS labs{matched_forms_select}
                FROM address_structures ast
                JOIN addresses a ON a.id = ast.address_id
                WHERE {where}
                ORDER BY a.pub_count DESC, a.id
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            binds,
        ).all()

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": [dict(r._mapping) for r in rows],
        }
