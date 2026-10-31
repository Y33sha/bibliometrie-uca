"""Date de fin d'embargo portée par la copie

La date de fin d'embargo passe de `source_records` à `source_record_locations`. Les copies HAL sous embargo reprennent la date de leur enregistrement source. Une copie à fichier déposé redevient ouverte (`is_oa`) : l'embargo seul la ferme, jusqu'à sa date de fin.

Revision ID: 7c3e9a5b1d42
Revises: 4e8a1c6d2b95
Create Date: 2026-10-30 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c3e9a5b1d42"
down_revision: str | Sequence[str] | None = "4e8a1c6d2b95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources.source_record_locations ADD COLUMN embargo_until date")
    op.execute("""
        COMMENT ON COLUMN sources.source_record_locations.embargo_until IS
        'Date de fin d''embargo. La copie est fermée jusqu''à cette date.'
    """)
    op.execute("""
        UPDATE sources.source_record_locations l
        SET embargo_until = sr.embargo_until, is_oa = l.pdf_url IS NOT NULL
        FROM sources.source_records sr
        WHERE sr.id = l.source_record_id AND sr.source = 'hal' AND sr.embargo_until IS NOT NULL
    """)
    op.execute("ALTER TABLE sources.source_records DROP COLUMN embargo_until")


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_records ADD COLUMN embargo_until date")
    op.execute("""
        UPDATE sources.source_records sr SET embargo_until = l.embargo_until
        FROM (
            SELECT source_record_id, max(embargo_until) AS embargo_until
            FROM sources.source_record_locations
            WHERE embargo_until > current_date
            GROUP BY source_record_id
        ) l
        WHERE sr.id = l.source_record_id
    """)
    op.execute("""
        UPDATE sources.source_record_locations SET is_oa = false
        WHERE embargo_until > current_date
    """)
    op.execute("ALTER TABLE sources.source_record_locations DROP COLUMN embargo_until")
