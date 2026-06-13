"""journals.pub_count + publishers.pub_count materialises (publications in-perimeter)

Le filtre `with_pubs` (editeurs/revues ayant des publications UCA) et le tri par
nombre de publications rejouaient un scan des publications in-perimeter via
journals (~0,5 s). On materialise le compte : `journals.pub_count` = publications
in-perimeter in-scope de la revue ; `publishers.pub_count` = somme de ses revues.
`with_pubs` devient `WHERE pub_count > 0` (lecture des petites tables), affichage
et tri gratuits. Maintenu par le pipeline (apres le rollup in_perimeter, phase
authorships) et aux fusions admin (revues / editeurs).

Revision ID: a1f3c8e2d5b9
Revises: f4b9d2e7a1c6
Create Date: 2026-06-12 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f3c8e2d5b9"
down_revision: str | Sequence[str] | None = "f4b9d2e7a1c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE journals ADD COLUMN pub_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE publishers ADD COLUMN pub_count integer NOT NULL DEFAULT 0")
    op.execute("""
        WITH counts AS (
            SELECT journal_id, COUNT(*) AS n
            FROM publications
            WHERE in_perimeter
              AND doc_type NOT IN ('memoir', 'peer_review')
              AND journal_id IS NOT NULL
            GROUP BY journal_id
        )
        UPDATE journals j SET pub_count = c.n
        FROM counts c WHERE c.journal_id = j.id
    """)
    op.execute("""
        WITH counts AS (
            SELECT publisher_id, SUM(pub_count) AS n
            FROM journals
            WHERE publisher_id IS NOT NULL
            GROUP BY publisher_id
        )
        UPDATE publishers p SET pub_count = c.n
        FROM counts c WHERE c.publisher_id = p.id
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE publishers DROP COLUMN IF EXISTS pub_count")
    op.execute("ALTER TABLE journals DROP COLUMN IF EXISTS pub_count")
