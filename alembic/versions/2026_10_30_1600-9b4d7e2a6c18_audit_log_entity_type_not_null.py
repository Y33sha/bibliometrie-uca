"""Contrainte NOT NULL de entity_type, au nom de la colonne

La contrainte `NOT NULL` de `ops.audit_log.entity_type` s'appelle `audit_log_entity_type_not_null`.

Revision ID: 9b4d7e2a6c18
Revises: 6c2e9a4f1b73
Create Date: 2026-10-30 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9b4d7e2a6c18"
down_revision: str | Sequence[str] | None = "6c2e9a4f1b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ops.audit_log RENAME CONSTRAINT audit_log_aggregate_type_not_null TO audit_log_entity_type_not_null"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ops.audit_log RENAME CONSTRAINT audit_log_entity_type_not_null TO audit_log_aggregate_type_not_null"
    )
