"""Décisions de rattachement par titre, une par titre normalisé

Revision ID: e7c3a9d1f482
Revises: d5b8f2a3c917
Create Date: 2026-10-31 23:00:00.000000

Une revue sans ISSN correspond à un titre normalisé : `serial_title_decisions` perd son éditeur. Un titre présent dans plusieurs décisions garde la plus récente.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7c3a9d1f482"
down_revision: str | Sequence[str] | None = "d5b8f2a3c917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM publishing.serial_title_decisions d
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY title_normalized ORDER BY created_at DESC, id DESC
            ) AS rank
            FROM publishing.serial_title_decisions
        ) ranked
        WHERE d.id = ranked.id AND ranked.rank > 1;

        ALTER TABLE publishing.serial_title_decisions DROP CONSTRAINT uq_serial_title_decisions;
        ALTER TABLE publishing.serial_title_decisions DROP COLUMN publisher_id;
        ALTER TABLE publishing.serial_title_decisions
            ADD CONSTRAINT uq_serial_title_decisions UNIQUE (title_normalized);

        COMMENT ON TABLE publishing.serial_title_decisions IS
        'Fusions décidées par l''administration : une série sans ISSN de ce titre normalisé est rattachée à la revue.';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE publishing.serial_title_decisions DROP CONSTRAINT uq_serial_title_decisions;
        ALTER TABLE publishing.serial_title_decisions
            ADD COLUMN publisher_id integer REFERENCES publishing.publishers(id) ON DELETE CASCADE;
        ALTER TABLE publishing.serial_title_decisions
            ADD CONSTRAINT uq_serial_title_decisions UNIQUE NULLS NOT DISTINCT
                (title_normalized, publisher_id);

        COMMENT ON TABLE publishing.serial_title_decisions IS
        'Fusions décidées par l''administration : une série sans ISSN, de ce titre normalisé et de cet éditeur, est rattachée à la revue.';
    """)
