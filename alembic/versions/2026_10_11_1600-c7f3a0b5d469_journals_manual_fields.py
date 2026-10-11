"""Les champs d'une revue saisis à la main

`journals.manual_fields` liste les champs que l'administration a saisis : le pipeline ne les écrit pas.

Reprise depuis le journal d'audit : une revue dont le type est encore le dernier saisi à la main (`journal.updated`) reçoit le marqueur du type.

Revision ID: c7f3a0b5d469
Revises: b6e2f9a4c358
Create Date: 2026-10-11 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7f3a0b5d469"
down_revision: str | Sequence[str] | None = "b6e2f9a4c358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE journals ADD COLUMN manual_fields text[] NOT NULL DEFAULT '{}'")
    op.execute("""
        WITH last_edit AS (
            SELECT DISTINCT ON (aggregate_id) aggregate_id, payload->>'journal_type' AS journal_type
            FROM audit_log
            WHERE event_type = 'journal.updated' AND payload ? 'journal_type'
            ORDER BY aggregate_id, id DESC
        )
        UPDATE journals j SET manual_fields = '{journal_type}'
        FROM last_edit e
        WHERE j.id = e.aggregate_id AND j.journal_type::text = e.journal_type
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE journals DROP COLUMN manual_fields")
