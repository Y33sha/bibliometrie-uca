"""`publications.publication_author_alignment` : recouvrement des listes d'auteurs de chaque publication à plusieurs notices

Vue matérialisée, rafraîchie en fin de phase `author_grouping`. Elle sert la file des fusions suspectes.

Revision ID: 5c1d8e3a7f20
Revises: 4b8e1c6f2d95
Create Date: 2026-10-18 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5c1d8e3a7f20"
down_revision: str | Sequence[str] | None = "4b8e1c6f2d95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.execute("""
        COMMENT ON MATERIALIZED VIEW publications.publication_author_alignment IS
            'Recouvrement des listes d''auteurs des publications à plusieurs notices. rule_aligned_signatures : signatures d''auteur d''un groupe dont un membre est lié par la règle (nom, identifiant, ordre). lone_signatures : signatures d''auteur seules dans leur groupe. model_signatures : signatures d''auteur liées à leur groupe par le modèle ; min_margin : plus petite marge de ces liens, en bits.'
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW publications.publication_author_alignment")
