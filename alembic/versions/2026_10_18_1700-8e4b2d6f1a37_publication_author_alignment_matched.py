"""`publications.publication_author_alignment` : signatures d'auteur qui ont un correspondant dans une autre notice

La vue compte, par publication à plusieurs notices, les signatures d'auteur dont le groupe réunit au moins deux signatures, quel que soit le moyen de liaison.

Revision ID: 8e4b2d6f1a37
Revises: 5c1d8e3a7f20
Create Date: 2026-10-18 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8e4b2d6f1a37"
down_revision: str | Sequence[str] | None = "5c1d8e3a7f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW publications.publication_author_alignment")
    op.execute("""
        CREATE MATERIALIZED VIEW publications.publication_author_alignment AS
        WITH author_members AS (
            SELECT g.publication_id, gs.group_id, gs.source_publication_id,
                   count(*) OVER (PARTITION BY gs.group_id) AS group_size
            FROM publications.grouped_source_authorships gs
            JOIN publications.source_authorship_groups g ON g.id = gs.group_id
            JOIN sources.source_authorships sa ON sa.id = gs.source_authorship_id
            WHERE sa.roles IS NULL OR 'author' = ANY(sa.roles)
        )
        SELECT publication_id,
               count(DISTINCT source_publication_id) AS notices,
               count(*) AS signatures,
               count(*) FILTER (WHERE group_size >= 2) AS matched_signatures
        FROM author_members
        GROUP BY publication_id
        HAVING count(DISTINCT source_publication_id) >= 2
    """)
    op.execute(
        "CREATE UNIQUE INDEX publication_author_alignment_pkey"
        " ON publications.publication_author_alignment (publication_id)"
    )
    op.execute("""
        COMMENT ON MATERIALIZED VIEW publications.publication_author_alignment IS
            'Recouvrement des listes d''auteurs des publications à plusieurs notices. matched_signatures : signatures d''auteur qui ont un correspondant dans une autre notice.'
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW publications.publication_author_alignment")
    op.execute("""
        CREATE MATERIALIZED VIEW publications.publication_author_alignment AS
        WITH author_members AS (
            SELECT g.publication_id, gs.group_id, gs.source_publication_id, gs.method, gs.margin,
                   count(*) OVER (PARTITION BY gs.group_id) AS group_size,
                   bool_or(gs.method IN ('name', 'identifier', 'order'))
                       OVER (PARTITION BY gs.group_id) AS rule_linked
            FROM publications.grouped_source_authorships gs
            JOIN publications.source_authorship_groups g ON g.id = gs.group_id
            JOIN sources.source_authorships sa ON sa.id = gs.source_authorship_id
            WHERE sa.roles IS NULL OR 'author' = ANY(sa.roles)
        )
        SELECT publication_id,
               count(DISTINCT source_publication_id) AS notices,
               count(*) AS signatures,
               count(DISTINCT group_id) AS groups,
               count(*) FILTER (WHERE rule_linked) AS rule_aligned_signatures,
               count(*) FILTER (WHERE group_size = 1) AS lone_signatures,
               count(*) FILTER (WHERE method = 'model') AS model_signatures,
               min(margin) AS min_margin
        FROM author_members
        GROUP BY publication_id
        HAVING count(DISTINCT source_publication_id) >= 2
    """)
    op.execute(
        "CREATE UNIQUE INDEX publication_author_alignment_pkey"
        " ON publications.publication_author_alignment (publication_id)"
    )
