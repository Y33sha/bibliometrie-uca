"""`source_authorships.duplicate_of` : signature copiée dans la liste d'auteurs de sa notice, vers la première occurrence de son nom

La phase `author_grouping` l'écrit ; l'alignement et la résolution des personnes écartent les signatures copiées.

Revision ID: 7d3b5e9a1c42
Revises: 2f7c9a1e4b58
Create Date: 2026-10-18 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7d3b5e9a1c42"
down_revision: str | Sequence[str] | None = "2f7c9a1e4b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_authorships
            ADD COLUMN duplicate_of integer
                REFERENCES sources.source_authorships (id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX source_authorships_duplicate_of_idx
            ON sources.source_authorships (duplicate_of) WHERE duplicate_of IS NOT NULL
    """)
    op.execute("""
        COMMENT ON COLUMN sources.source_authorships.duplicate_of IS
            'Signature dont celle-ci est la copie, dans une liste d''auteurs recopiée par la source. Écrite par la phase author_grouping.'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_authorships DROP COLUMN duplicate_of")
