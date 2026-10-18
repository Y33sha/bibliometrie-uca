"""`source_publications.author_count` et `distinct_author_count` : signatures d'auteur individuelles de la notice, et noms complets distincts parmi elles

Zéro par défaut ; le oneshot `backfill_author_counts` les calcule pour le stock, la normalisation les tient à jour.

Revision ID: 2f7c9a1e4b58
Revises: 8e4b2d6f1a37
Create Date: 2026-10-18 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2f7c9a1e4b58"
down_revision: str | Sequence[str] | None = "8e4b2d6f1a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_publications
            ADD COLUMN author_count integer NOT NULL DEFAULT 0,
            ADD COLUMN distinct_author_count integer NOT NULL DEFAULT 0
    """)
    op.execute("""
        COMMENT ON COLUMN sources.source_publications.author_count IS
            'Signatures de la notice qui ont le rôle author et ne sont pas collectives, telles que la source les donne.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.source_publications.distinct_author_count IS
            'Noms complets normalisés distincts parmi les signatures comptées par author_count.'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_publications
            DROP COLUMN author_count,
            DROP COLUMN distinct_author_count
    """)
