"""Cas de retrait DOI_D_UNE_AUTRE_OEUVRE, toutes sources

Revision ID: 662b5308f866
Revises: 6ebcc420521d
Create Date: 2026-11-01 17:00:00.000000

Le retrait du DOI d'une autre œuvre vise tout enregistrement source autre que Crossref. Le cas inscrit dans `source_record_identifiers.removed_by` prend un nom sans référence à HAL.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "662b5308f866"
down_revision: str | Sequence[str] | None = "6ebcc420521d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE sources.source_record_identifiers SET removed_by = 'DOI_D_UNE_AUTRE_OEUVRE'"
        " WHERE removed_by = 'HAL_DOI_D_UNE_AUTRE_OEUVRE'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sources.source_record_identifiers SET removed_by = 'HAL_DOI_D_UNE_AUTRE_OEUVRE'"
        " WHERE removed_by = 'DOI_D_UNE_AUTRE_OEUVRE'"
    )
