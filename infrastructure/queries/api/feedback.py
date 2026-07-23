"""Query services du tableau de bord admin : feedback sur la détection d'adresses."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.addresses_queries import AddressStructureSummary
from application.ports.api.feedback_queries import (
    FeedbackAddressesResponse,
    FeedbackAddressItem,
    FeedbackMatchedForm,
    FeedbackQueries,
    FeedbackStats,
)
from infrastructure.queries.api.addresses import address_structures_json

# Les cas de la détection d'adresses, croisant l'arbitrage humain (`is_confirmed`) et ce que la
# détection a proposé (`matched_form_id`), sur un lien `address_structures` aliasé `ast`. Partagés
# entre le décompte (`feedback_stats`) et les listes (faux négatifs / faux positifs).
_CONCORDANT_VALID = "ast.is_confirmed = TRUE AND ast.matched_form_id IS NOT NULL"
_CONCORDANT_REJECTED = "ast.is_confirmed = FALSE AND ast.matched_form_id IS NULL"
_FALSE_NEGATIVE = "ast.is_confirmed = TRUE AND ast.matched_form_id IS NULL"
_FALSE_POSITIVE = "ast.is_confirmed = FALSE AND ast.matched_form_id IS NOT NULL"
_PENDING = "ast.is_confirmed IS NULL AND ast.matched_form_id IS NOT NULL"


class PgFeedbackQueries(FeedbackQueries):
    """Adapter SA pour `FeedbackQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def feedback_stats(self, structure_id: int) -> FeedbackStats:
        row = self._conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE {_CONCORDANT_VALID}) AS concordant_valid,
                    COUNT(*) FILTER (WHERE {_CONCORDANT_REJECTED}) AS concordant_rejected,
                    COUNT(*) FILTER (WHERE {_FALSE_NEGATIVE}) AS false_negatives,
                    COUNT(*) FILTER (WHERE {_FALSE_POSITIVE}) AS false_positives,
                    COUNT(*) FILTER (WHERE {_PENDING}) AS pending
                FROM address_structures ast
                WHERE ast.structure_id = :sid
            """),
            {"sid": structure_id},
        ).one()
        concordant_valid = row.concordant_valid or 0
        concordant_rejected = row.concordant_rejected or 0
        false_negatives = row.false_negatives or 0
        false_positives = row.false_positives or 0
        reviewed = concordant_valid + concordant_rejected + false_negatives + false_positives
        concordant = concordant_valid + concordant_rejected
        return FeedbackStats(
            total_reviewed=reviewed,
            detection_rate=round(concordant / reviewed * 100, 1) if reviewed else None,
            false_negatives=false_negatives,
            false_positives=false_positives,
            concordant_valid=concordant_valid,
            pending=row.pending or 0,
        )

    def feedback_false_negatives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> FeedbackAddressesResponse:
        return self._feedback_paginated(
            structure_id=structure_id,
            page=page,
            per_page=per_page,
            search=search,
            kind_where=_FALSE_NEGATIVE,
            with_matched_forms=False,
        )

    def feedback_false_positives(
        self, *, structure_id: int, page: int, per_page: int, search: str
    ) -> FeedbackAddressesResponse:
        return self._feedback_paginated(
            structure_id=structure_id,
            page=page,
            per_page=per_page,
            search=search,
            kind_where=_FALSE_POSITIVE,
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
    ) -> FeedbackAddressesResponse:
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
                    'structure', json_build_object('acronym', s.acronym, 'name', s.name)
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
                    ({address_structures_json("a.id")}) AS structures{matched_forms_select}
                FROM address_structures ast
                JOIN addresses a ON a.id = ast.address_id
                WHERE {where}
                ORDER BY a.pub_count DESC, a.id
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            binds,
        ).all()

        addresses = [
            FeedbackAddressItem(
                id=r.id,
                raw_text=r.raw_text,
                pub_count=r.pub_count,
                structures=[
                    AddressStructureSummary.model_validate(s) for s in (r.structures or [])
                ],
                matched_forms=(
                    [FeedbackMatchedForm(**mf) for mf in (r.matched_forms or [])]
                    if with_matched_forms
                    else None
                ),
            )
            for r in rows
        ]

        return FeedbackAddressesResponse(
            total=total,
            page=page,
            per_page=per_page,
            addresses=addresses,
        )
