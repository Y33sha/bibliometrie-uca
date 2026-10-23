"""File d'attente de la détection des pays des adresses : address_candidates_queue

Revision ID: c1298df84ca1
Revises: 4b6efac6c4e1
Create Date: 2026-10-23 14:00:00.000000

La file reçoit les adresses marquées par `addresses.candidates_dirty`, puis la colonne et son index partiel sont supprimés.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1298df84ca1"
down_revision: str | Sequence[str] | None = "4b6efac6c4e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE queues.address_candidates_queue (
            id integer PRIMARY KEY REFERENCES structures.addresses (id) ON DELETE CASCADE,
            seq bigint GENERATED ALWAYS AS IDENTITY
        );
        INSERT INTO queues.address_candidates_queue (id)
        SELECT id FROM structures.addresses WHERE candidates_dirty;
        DROP INDEX structures.idx_addresses_candidates_dirty;
        ALTER TABLE structures.addresses DROP COLUMN candidates_dirty;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE structures.addresses ADD COLUMN candidates_dirty boolean DEFAULT false NOT NULL;
        COMMENT ON COLUMN structures.addresses.candidates_dirty IS
            'Adresse à traiter : détection du pays par le texte, puis résolution des candidats.';
        UPDATE structures.addresses SET candidates_dirty = true
        WHERE id IN (SELECT id FROM queues.address_candidates_queue);
        ALTER TABLE structures.addresses ALTER COLUMN candidates_dirty SET DEFAULT true;
        CREATE INDEX idx_addresses_candidates_dirty
            ON structures.addresses USING btree (id) WHERE candidates_dirty;
        DROP TABLE queues.address_candidates_queue;
    """)
