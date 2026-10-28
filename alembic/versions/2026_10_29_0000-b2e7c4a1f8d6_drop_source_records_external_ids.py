"""Colonne external_ids des enregistrements sources supprimée

Revision ID: b2e7c4a1f8d6
Revises: a9d3f7c1e5b4
Create Date: 2026-10-29 00:00:00.000000

Les identifiants des enregistrements sources sont dans `source_record_identifiers`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2e7c4a1f8d6"
down_revision: str | Sequence[str] | None = "a9d3f7c1e5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources.source_records DROP COLUMN external_ids;")


def downgrade() -> None:
    """La colonne revient vide : son contenu se recalcule seulement avec le code qui l'écrivait."""
    op.execute("""
        ALTER TABLE sources.source_records
            ADD COLUMN external_ids jsonb DEFAULT '{}'::jsonb NOT NULL,
            ADD CONSTRAINT source_records_external_ids_is_object
                CHECK (jsonb_typeof(external_ids) = 'object');
    """)
