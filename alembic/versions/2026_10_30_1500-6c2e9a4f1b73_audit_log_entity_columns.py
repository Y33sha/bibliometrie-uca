"""Colonnes de l'entité affectée dans le journal d'audit

`ops.audit_log.aggregate_type` et `aggregate_id` deviennent `entity_type` et `entity_id`, et leur index `audit_log_entity_idx`. Le commentaire de `entity_type` liste les types que l'application émet.

Revision ID: 6c2e9a4f1b73
Revises: 3f8a1c6d2e47
Create Date: 2026-10-30 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6c2e9a4f1b73"
down_revision: str | Sequence[str] | None = "3f8a1c6d2e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TYPE_COMMENT = "Type de l'entité affectée : address, config, perimeter, person, publication, publisher, serial, structure."
_AGGREGATE_TYPE_COMMENT = (
    "Type de l'entité affectée : address, journal, perimeter, person, publication, structure."
)


def upgrade() -> None:
    op.alter_column("audit_log", "aggregate_type", new_column_name="entity_type", schema="ops")
    op.alter_column("audit_log", "aggregate_id", new_column_name="entity_id", schema="ops")
    op.execute("ALTER INDEX ops.audit_log_aggregate_idx RENAME TO audit_log_entity_idx")
    op.alter_column(
        "audit_log",
        "entity_type",
        existing_type=sa.Text(),
        comment=_ENTITY_TYPE_COMMENT,
        schema="ops",
    )


def downgrade() -> None:
    op.alter_column(
        "audit_log",
        "entity_type",
        existing_type=sa.Text(),
        comment=_AGGREGATE_TYPE_COMMENT,
        schema="ops",
    )
    op.execute("ALTER INDEX ops.audit_log_entity_idx RENAME TO audit_log_aggregate_idx")
    op.alter_column("audit_log", "entity_id", new_column_name="aggregate_id", schema="ops")
    op.alter_column("audit_log", "entity_type", new_column_name="aggregate_type", schema="ops")
