"""Entrées de retrait d'identifiants retirées de `corrections`

Revision ID: b8e3c1d7a4f2
Revises: d7b2f4a9c1e3
Create Date: 2026-10-28 20:00:00.000000

`source_record_identifiers.removed_by` donne la règle de correction qui retire un identifiant. Les entrées `external_ids` et `removed_external_ids` de `source_records.corrections` sont supprimées.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8e3c1d7a4f2"
down_revision: str | Sequence[str] | None = "d7b2f4a9c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE sources.source_records
        SET corrections = corrections - 'external_ids' - 'removed_external_ids'
        WHERE corrections ?| ARRAY['external_ids', 'removed_external_ids'];
    """)


def downgrade() -> None:
    """Les entrées supprimées se recalculent seulement avec le code qui les écrivait."""
