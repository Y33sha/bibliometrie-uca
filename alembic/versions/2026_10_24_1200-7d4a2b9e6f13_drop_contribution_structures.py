"""Suppression de la vue contribution_structures

Revision ID: 7d4a2b9e6f13
Revises: 3c8e1f5a9d27
Create Date: 2026-10-24 12:00:00.000000

Les lecteurs des structures d'une contribution lisent `group_structures`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7d4a2b9e6f13"
down_revision: str | Sequence[str] | None = "3c8e1f5a9d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW publications.contribution_structures")


def downgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW publications.contribution_structures AS
        SELECT DISTINCT a.id AS contribution_id, sas.structure_id
        FROM sources.source_contribution_structures sas
        JOIN sources.source_contributions sa ON sa.id = sas.source_contribution_id
        JOIN sources.source_records sp ON sp.id = sa.source_record_id
        JOIN publications.contributions a
            ON a.publication_id = sp.publication_id AND a.person_id = sa.person_id
        WHERE NOT EXISTS (
            SELECT 1 FROM persons.persons pe WHERE pe.id = a.person_id AND pe.exclusion IS NOT NULL
        )
        WITH DATA;

        CREATE UNIQUE INDEX contribution_structures_pkey
            ON publications.contribution_structures (contribution_id, structure_id);
        CREATE INDEX idx_contribution_structures_structure_id
            ON publications.contribution_structures (structure_id);
    """)
