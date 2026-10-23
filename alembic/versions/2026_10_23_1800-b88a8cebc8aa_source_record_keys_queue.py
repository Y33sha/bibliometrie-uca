"""File d'attente de la réconciliation des publications : source_record_keys_queue

Revision ID: b88a8cebc8aa
Revises: b36ce1125278
Create Date: 2026-10-23 18:00:00.000000

La file reçoit les enregistrements sources marqués par `source_records.keys_dirty`, puis la colonne et son index partiel sont supprimés.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b88a8cebc8aa"
down_revision: str | Sequence[str] | None = "b36ce1125278"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE queues.source_record_keys_queue (
            id integer PRIMARY KEY REFERENCES sources.source_records (id) ON DELETE CASCADE,
            seq bigint GENERATED ALWAYS AS IDENTITY
        );
        INSERT INTO queues.source_record_keys_queue (id)
        SELECT id FROM sources.source_records WHERE keys_dirty;
        DROP INDEX sources.idx_source_records_keys_dirty;
        ALTER TABLE sources.source_records DROP COLUMN keys_dirty;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_records ADD COLUMN keys_dirty boolean DEFAULT false NOT NULL;
        UPDATE sources.source_records SET keys_dirty = true
        WHERE id IN (SELECT id FROM queues.source_record_keys_queue);
        ALTER TABLE sources.source_records ALTER COLUMN keys_dirty SET DEFAULT true;
        CREATE INDEX idx_source_records_keys_dirty
            ON sources.source_records USING btree (keys_dirty) WHERE keys_dirty;
        DROP TABLE queues.source_record_keys_queue;
    """)
