"""Index de `grouped_source_authorships.source_publication_id`

La clé étrangère vers `source_publications` supprime en cascade. L'index sert cette cascade quand une notice est supprimée.

Revision ID: 5b7e2d9c4a18
Revises: 3c6e8a1f5d27
Create Date: 2026-10-19 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5b7e2d9c4a18"
down_revision: str | Sequence[str] | None = "3c6e8a1f5d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_grouped_source_authorships_source_publication_id",
        "grouped_source_authorships",
        ["source_publication_id"],
        schema="publications",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_grouped_source_authorships_source_publication_id",
        table_name="grouped_source_authorships",
        schema="publications",
    )
