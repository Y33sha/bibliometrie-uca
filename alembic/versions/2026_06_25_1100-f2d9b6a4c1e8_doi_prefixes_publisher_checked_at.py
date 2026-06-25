"""doi_prefixes.publisher_checked_at : marqueur « /prefixes déjà tenté »

Le chantier resolve-ra-amont scinde la résolution : `resolve_ra` (avant cross_imports)
n'insère que `(prefix, ra)` ; le volet publisher (phase `publishers_journals`) interroge
ensuite `/prefixes` pour nommer/attacher le publisher. La garde « tenté une seule fois »
était jusqu'ici implicite (la résolution `/prefixes` se faisait à la création de la row,
jamais retentée). En déplaçant `/prefixes` vers le volet, il faut un marqueur explicite :
`publisher_checked_at` NULL = `/prefixes` jamais tenté pour cette row.

Backfill : les rows existantes ont déjà été traitées par l'ancien flux (publisher résolu
ou abandonné) → `publisher_checked_at = fetched_at` les rend terminales, le volet les
ignore (pas de re-query du backlog). Les rows créées ensuite par `resolve_ra` ont la
colonne NULL → le volet les traite une fois.

Revision ID: f2d9b6a4c1e8
Revises: e1c7a4f9b3d6
Create Date: 2026-06-25 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2d9b6a4c1e8"
down_revision: str | Sequence[str] | None = "e1c7a4f9b3d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE doi_prefixes ADD COLUMN publisher_checked_at timestamptz")
    op.execute("UPDATE doi_prefixes SET publisher_checked_at = fetched_at")
    op.execute(
        "CREATE INDEX idx_doi_prefixes_publisher_pending ON doi_prefixes (prefix) "
        "WHERE publisher_id IS NULL AND publisher_checked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_doi_prefixes_publisher_pending")
    op.execute("ALTER TABLE doi_prefixes DROP COLUMN publisher_checked_at")
