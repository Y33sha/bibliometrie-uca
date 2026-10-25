"""ROR des publications, ancêtres compris

Revision ID: c7a4e1d9f352
Revises: b5e2c8f4a917
Create Date: 2026-10-26 11:00:00.000000

La vue matérialisée `publication_rors` réunit les ROR de tous les auteurs d'une publication : ceux que les sources donnent pour les contributions sources alignées, et ceux des structures reconnues par la phase `affiliations`. Une contribution sans personne en est ; celle d'une personne qui n'en est pas une (`not_a_person`) en est exclue. Chaque ROR entre avec ses ancêtres de `ror_relations` ; `cited` distingue les ROR cités des ancêtres ajoutés. La phase `finalize` la rafraîchit.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7a4e1d9f352"
down_revision: str | Sequence[str] | None = "b5e2c8f4a917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW publications.publication_rors AS
        WITH RECURSIVE cited AS (
            SELECT c.publication_id, r.ror_id
            FROM publications.contributions c
            JOIN publications.aligned_source_contributions m ON m.contribution_id = c.id
            JOIN sources.source_contribution_rors r
                ON r.source_contribution_id = m.source_contribution_id
            LEFT JOIN persons.persons pe ON pe.id = c.person_id
            WHERE c.roles && ARRAY['author'::text]
              AND pe.exclusion IS DISTINCT FROM 'not_a_person'
            UNION
            SELECT ps.publication_id, s.ror_id
            FROM publications.publication_structures ps
            JOIN structures.structures s ON s.id = ps.structure_id
            WHERE s.ror_id IS NOT NULL
        ),
        lineage AS (
            SELECT publication_id, ror_id, true AS cited FROM cited
            UNION
            SELECT l.publication_id, rr.parent_ror_id, false
            FROM lineage l
            JOIN ref.ror_relations rr ON rr.child_ror_id = l.ror_id
        )
        SELECT publication_id, ror_id, bool_or(cited) AS cited
        FROM lineage
        GROUP BY publication_id, ror_id
        WITH DATA;

        CREATE UNIQUE INDEX publication_rors_pkey
            ON publications.publication_rors (publication_id, ror_id);
        CREATE INDEX idx_publication_rors_ror ON publications.publication_rors (ror_id);
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW publications.publication_rors")
