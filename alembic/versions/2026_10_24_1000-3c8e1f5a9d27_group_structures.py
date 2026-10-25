"""Structures des groupes de contributions sources : group_structures

Revision ID: 3c8e1f5a9d27
Revises: 0f2760ea662f
Create Date: 2026-10-24 10:00:00.000000

`group_structures` relie un groupe rattaché à une personne non exclue aux structures de ses membres. `publication_structures` se calcule sur les groupes d'auteur et `group_structures`. `contribution_structures` reste en place pour ses lecteurs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3c8e1f5a9d27"
down_revision: str | Sequence[str] | None = "0f2760ea662f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PUBLICATION_STRUCTURES_INDEXES = """
    CREATE UNIQUE INDEX publication_structures_publication_structure
        ON publications.publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publications.publication_structures (structure_id);
"""


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW publications.group_structures AS
        SELECT DISTINCT m.group_id, scs.structure_id
        FROM sources.source_contribution_structures scs
        JOIN publications.source_contribution_group_members m
            ON m.source_contribution_id = scs.source_contribution_id
        JOIN publications.source_contribution_groups g ON g.id = m.group_id
        JOIN persons.persons pe ON pe.id = g.person_id
        WHERE pe.exclusion IS NULL
        WITH DATA;

        CREATE UNIQUE INDEX group_structures_pkey
            ON publications.group_structures (group_id, structure_id);
        CREATE INDEX idx_group_structures_structure_id
            ON publications.group_structures (structure_id);

        DROP MATERIALIZED VIEW publications.publication_structures;
        CREATE MATERIALIZED VIEW publications.publication_structures AS
        SELECT DISTINCT g.publication_id, gs.structure_id
        FROM publications.source_contribution_groups g
        JOIN publications.group_structures gs ON gs.group_id = g.id
        WHERE g.roles && ARRAY['author']
        WITH DATA;
    """)
    op.execute(_PUBLICATION_STRUCTURES_INDEXES)


def downgrade() -> None:
    op.execute("""
        DROP MATERIALIZED VIEW publications.publication_structures;
        CREATE MATERIALIZED VIEW publications.publication_structures AS
        SELECT DISTINCT a.publication_id, aus.structure_id
        FROM publications.contributions a
        JOIN publications.contribution_structures aus ON aus.contribution_id = a.id
        WHERE a.roles && ARRAY['author']
        WITH DATA;

        DROP MATERIALIZED VIEW publications.group_structures;
    """)
    op.execute(_PUBLICATION_STRUCTURES_INDEXES)
