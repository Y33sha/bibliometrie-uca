"""source_authorships : suppression de l'index mort `idx_sa_nonhal_outscope`

Index partiel `(source_publication_id, author_position) WHERE source <> 'hal'
AND in_perimeter = false`, jamais utilisé (0 scan sur toute la durée de vie de
la base) pour 178 Mo. Il alourdissait la maintenance à chaque INSERT/DELETE de
`source_authorships` non-HAL (WoS, OpenAlex, ScanR, crossref, theses) sans
servir aucune lecture.

Revision ID: d5e8b3a1f6c4
Revises: a2c6e4f8b1d7
Create Date: 2026-06-02 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5e8b3a1f6c4"
down_revision: str | Sequence[str] | None = "a2c6e4f8b1d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sa_nonhal_outscope")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX idx_sa_nonhal_outscope ON source_authorships "
        "(source_publication_id, author_position) "
        "WHERE source <> 'hal'::source_type AND in_perimeter = false"
    )
