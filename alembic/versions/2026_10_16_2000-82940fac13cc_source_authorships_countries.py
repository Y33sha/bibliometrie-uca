"""Pays des signatures

`source_authorships.countries` réunit les pays retenus des adresses de la signature, les pays de ses organisations ROR sans texte d'affiliation et ceux de ses structures HAL. Les pays d'une notice en dérivent. `fill_signature_countries` remplit la colonne pour le stock.

Revision ID: 82940fac13cc
Revises: 8ea28dc97edf
Create Date: 2026-10-16 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "82940fac13cc"
down_revision: str | Sequence[str] | None = "8ea28dc97edf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_authorships ADD COLUMN countries text[];
        COMMENT ON COLUMN sources.source_authorships.countries IS
            'Pays de la signature : pays retenus de ses adresses, de ses organisations ROR sans adresse et de ses structures HAL.';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_authorships DROP COLUMN countries")
