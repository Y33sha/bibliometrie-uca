"""Remplissage de `publications.impact`

Revision ID: bd1b33b622f8
Revises: 49a8d5ba9cee
Create Date: 2026-11-01 18:10:00.000000

Chaque publication reçoit les indicateurs de citation de son premier enregistrement source OpenAlex, preprints après les autres. La consolidation applique ensuite sa règle exacte à chaque recalcul : elle garde le preprint en tête d'une publication sans version publiée.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bd1b33b622f8"
down_revision: str | Sequence[str] | None = "49a8d5ba9cee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE publications.publications p SET impact = sr.impact
        FROM (
            SELECT DISTINCT ON (publication_id) publication_id, impact
            FROM sources.source_records
            WHERE source = 'openalex' AND publication_id IS NOT NULL
            ORDER BY publication_id, coalesce(doc_type = 'preprint', false), id
        ) sr
        WHERE p.id = sr.publication_id
    """)


def downgrade() -> None:
    op.execute("UPDATE publications.publications SET impact = NULL WHERE impact IS NOT NULL")
