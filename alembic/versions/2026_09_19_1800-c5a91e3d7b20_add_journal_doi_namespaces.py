"""Crée la table journal_doi_namespaces

Un espace de noms DOI (`10.1016/j.physletb.`) désigne une revue. La phase `publishers_journals` recalcule la table d'après les enregistrements de toutes les sources.

Revision ID: c5a91e3d7b20
Revises: e2b7f4c8a913
Create Date: 2026-09-19 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a91e3d7b20"
down_revision: str | Sequence[str] | None = "e2b7f4c8a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journal_doi_namespaces",
        sa.Column("namespace", sa.Text(), primary_key=True),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dois", sa.Integer(), nullable=False),
        sa.Column("share", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_journal_doi_namespaces_journal_id", "journal_doi_namespaces", ["journal_id"]
    )


def downgrade() -> None:
    op.drop_table("journal_doi_namespaces")
