"""`publications.authorships_dirty` : publications dont les groupes de signatures sont à recalculer

Vrai par défaut : toute publication existante est à grouper au premier passage de la phase des groupes.

Revision ID: 4b8e1c6f2d95
Revises: 7d2f9b4e1a63
Create Date: 2026-10-18 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4b8e1c6f2d95"
down_revision: str | Sequence[str] | None = "7d2f9b4e1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE publications.publications"
        " ADD COLUMN authorships_dirty boolean NOT NULL DEFAULT true"
    )
    op.execute(
        "CREATE INDEX publications_authorships_dirty_idx ON publications.publications (id)"
        " WHERE authorships_dirty"
    )
    op.execute("""
        COMMENT ON COLUMN publications.publications.authorships_dirty IS
            'Groupes de signatures à recalculer : une notice a rejoint ou quitté la publication, ou ses signatures ont changé.'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX publications.publications_authorships_dirty_idx")
    op.execute("ALTER TABLE publications.publications DROP COLUMN authorships_dirty")
