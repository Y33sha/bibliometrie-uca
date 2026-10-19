"""Verdicts d'Unpaywall par DOI, dans `sources.unpaywall`

La table conserve le statut open access qu'Unpaywall donne pour chaque DOI interrogé, et la date de l'interrogation. Le statut d'une publication se calcule à partir de ses sources et de ce verdict. `publications.unpaywall_checked_at` est retirée. La table part vide : chaque DOI est réinterrogé.

Revision ID: 8d4f1a2b6c3e
Revises: 5b7e2d9c4a18
Create Date: 2026-10-19 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

from alembic import op

revision: str = "8d4f1a2b6c3e"
down_revision: str | Sequence[str] | None = "5b7e2d9c4a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "unpaywall",
        sa.Column("doi", sa.Text(), primary_key=True),
        sa.Column(
            "oa_status",
            ENUM(name="oa_type", schema="public", create_type=False),
            nullable=True,
            comment="Statut open access donné par Unpaywall. NULL : DOI absent d'Unpaywall.",
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        schema="sources",
        comment=(
            "Verdict d'Unpaywall pour chaque DOI interrogé par la phase oa_status. Le DOI est "
            "réinterrogé quand checked_at date de plus que le délai unpaywall_recheck_after_days."
        ),
    )
    op.drop_column("publications", "unpaywall_checked_at", schema="publications")


def downgrade() -> None:
    op.add_column(
        "publications",
        sa.Column("unpaywall_checked_at", sa.DateTime(timezone=True), nullable=True),
        schema="publications",
    )
    op.create_index(
        "idx_pub_unpaywall_checked",
        "publications",
        [sa.text("unpaywall_checked_at NULLS FIRST")],
        schema="publications",
        postgresql_where=sa.text("doi IS NOT NULL"),
    )
    op.drop_table("unpaywall", schema="sources")
