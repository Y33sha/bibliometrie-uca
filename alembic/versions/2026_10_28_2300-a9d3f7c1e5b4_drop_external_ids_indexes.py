"""Index d'`external_ids` supprimés

Revision ID: a9d3f7c1e5b4
Revises: e6a1d4b8c2f9
Create Date: 2026-10-28 23:00:00.000000

Les requêtes lisent les identifiants des enregistrements sources dans `source_record_identifiers`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9d3f7c1e5b4"
down_revision: str | Sequence[str] | None = "e6a1d4b8c2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DROP INDEX sources.idx_source_records_external_ids;
        DROP INDEX sources.idx_source_records_nnt;
        DROP INDEX sources.idx_source_records_pmid;
    """)


def downgrade() -> None:
    op.execute("""
        CREATE INDEX idx_source_records_external_ids ON sources.source_records
            USING gin (external_ids) WHERE external_ids <> '{}'::jsonb;
        CREATE INDEX idx_source_records_nnt ON sources.source_records
            USING btree ((external_ids ->> 'nnt')) WHERE (external_ids ->> 'nnt') IS NOT NULL;
        CREATE INDEX idx_source_records_pmid ON sources.source_records
            USING btree ((external_ids ->> 'pmid')) WHERE (external_ids ->> 'pmid') IS NOT NULL;
    """)
