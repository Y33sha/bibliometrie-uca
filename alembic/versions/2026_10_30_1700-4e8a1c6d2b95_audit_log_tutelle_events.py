"""Événements de tutelle du journal d'audit nommés `structure_tutelle`

Les événements `structure_relation.created` et `structure_relation.deleted` s'appellent `structure_tutelle.created` et `structure_tutelle.deleted`. La clé `relation_id` de leur contenu s'appelle `tutelle_id`.

Revision ID: 4e8a1c6d2b95
Revises: 9b4d7e2a6c18
Create Date: 2026-10-30 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4e8a1c6d2b95"
down_revision: str | Sequence[str] | None = "9b4d7e2a6c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(old_prefix: str, new_prefix: str, old_key: str, new_key: str) -> None:
    op.execute(f"""
        UPDATE ops.audit_log
        SET event_type = '{new_prefix}' || substr(event_type, length('{old_prefix}') + 1),
            payload = CASE
                WHEN payload ? '{old_key}'
                THEN (payload - '{old_key}') || jsonb_build_object('{new_key}', payload -> '{old_key}')
                ELSE payload
            END
        WHERE event_type IN ('{old_prefix}created', '{old_prefix}deleted')
    """)


def upgrade() -> None:
    _rename("structure_relation.", "structure_tutelle.", "relation_id", "tutelle_id")


def downgrade() -> None:
    _rename("structure_tutelle.", "structure_relation.", "tutelle_id", "relation_id")
