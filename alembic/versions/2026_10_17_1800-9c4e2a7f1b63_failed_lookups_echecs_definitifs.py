"""Échecs définitifs de `failed_lookups` : identifiant absent de son registre

Le commentaire de `failed_lookups` et la description du réglage `fetch_missing_retry_after_days` nomment les échecs définitifs : hal-id dans HAL, NNT dans theses.fr, DOI inconnu de doi.org.

Revision ID: 9c4e2a7f1b63
Revises: 3e7a9c2d5b18
Create Date: 2026-10-17 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9c4e2a7f1b63"
down_revision: str | Sequence[str] | None = "3e7a9c2d5b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_COMMENT = (
    "Identifiants cherchés en vain par la phase fetch_missing, dans une source ou auprès de"
    " doi.org (source doi_org : DOI que doi.org ne connaît pas). L''échec est définitif pour un"
    " identifiant absent de son registre (hal-id dans HAL, NNT dans theses.fr, DOI auprès de"
    " doi.org). Les autres recherches reprennent quand not_found_at date de plus que le délai"
    " fetch_missing_retry_after_days."
)
_TABLE_COMMENT_BEFORE = (
    "Identifiants cherchés en vain par la phase fetch_missing, dans une source ou auprès de"
    " doi.org (source doi_org : DOI que doi.org ne connaît pas). La recherche reprend quand"
    " not_found_at date de plus que le délai fetch_missing_retry_after_days."
)
_DESCRIPTION = (
    "Délai, en jours, avant de chercher de nouveau un identifiant introuvable dans une source."
    " L''échec est définitif pour un identifiant absent de son registre (hal-id dans HAL, NNT"
    " dans theses.fr, DOI auprès de doi.org)."
)
_DESCRIPTION_BEFORE = (
    "Délai, en jours, avant de chercher de nouveau un identifiant introuvable dans une source."
    " L''échec sur un identifiant natif de la source est définitif."
)


def _apply(comment: str, description: str) -> None:
    op.execute(f"COMMENT ON TABLE sources.failed_lookups IS '{comment}'")
    op.execute(
        f"UPDATE ops.config SET description = '{description}'"
        " WHERE key = 'fetch_missing_retry_after_days'"
    )


def upgrade() -> None:
    _apply(_TABLE_COMMENT, _DESCRIPTION)


def downgrade() -> None:
    _apply(_TABLE_COMMENT_BEFORE, _DESCRIPTION_BEFORE)
