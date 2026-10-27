"""Ajout des fusions manuelles de publications

Revision ID: a4d9e2c7b318
Revises: f3c9a2e7b510
Create Date: 2026-10-27 15:30:00.000000

Une fusion manuelle réunit des enregistrements sources dans une même publication, sans clé de confirmation commune. La réconciliation lit ce verdict comme une clé de confirmation. Les enregistrements sources sont désignés par leur clé naturelle `(source, source_id)`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4d9e2c7b318"
down_revision: str | Sequence[str] | None = "f3c9a2e7b510"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE publications.manual_merges (
            id serial PRIMARY KEY,
            created_at timestamp with time zone DEFAULT now() NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE publications.manual_merge_source_records (
            manual_merge_id integer NOT NULL
                REFERENCES publications.manual_merges (id) ON DELETE CASCADE,
            source public.source_type NOT NULL,
            source_id text NOT NULL,
            CONSTRAINT manual_merge_source_records_pkey PRIMARY KEY (manual_merge_id, source, source_id)
        )
    """)
    op.execute(
        "CREATE INDEX idx_manual_merge_source_records_source_record "
        "ON publications.manual_merge_source_records (source, source_id)"
    )
    op.execute(
        "COMMENT ON TABLE publications.manual_merges IS "
        "'Fusions de publications décidées par l''administration.'"
    )
    op.execute(
        "COMMENT ON TABLE publications.manual_merge_source_records IS "
        "'Enregistrements sources d''une fusion manuelle, par clé naturelle. "
        "La réconciliation les réunit dans une même publication.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE publications.manual_merge_source_records")
    op.execute("DROP TABLE publications.manual_merges")
