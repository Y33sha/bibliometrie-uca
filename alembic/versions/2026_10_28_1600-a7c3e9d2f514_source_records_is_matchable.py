"""Enregistrements sources écartés de la réconciliation

`source_records.is_matchable` est faux pour un enregistrement source écarté de la réconciliation. La phase `metadata_correction` calcule la colonne.

Revision ID: a7c3e9d2f514
Revises: d2e7b4f9a1c3
Create Date: 2026-10-28 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e9d2f514"
down_revision: str | Sequence[str] | None = "d2e7b4f9a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_records",
        sa.Column(
            "is_matchable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment=(
                "Faux pour un enregistrement source écarté de la réconciliation : préfixe DOI exclu, "
                "titre de paratexte, enregistrement ScanR issu d'un dépôt HAL introuvable, "
                "enregistrement d'agrégateur sans DOI, lien ni clé de confirmation."
            ),
        ),
        schema="sources",
    )


def downgrade() -> None:
    op.drop_column("source_records", "is_matchable", schema="sources")
