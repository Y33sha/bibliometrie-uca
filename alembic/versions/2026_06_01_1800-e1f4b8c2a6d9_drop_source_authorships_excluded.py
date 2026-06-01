"""source_authorships : suppression de la colonne `excluded`

`source_authorships.excluded` était écrite par une unique fonctionnalité
admin (la croix « marquer comme faux » de la grille des sources, page
publication) jamais utilisée — 0 ligne à `true` en prod. Le rejet canonique
d'une authorship passe par `authorships.excluded` (conservée). On retire donc
la colonne source, son index partiel `idx_sa_excluded`, et tous les filtres
`NOT sa.excluded` du pipeline et des queries.

Revision ID: e1f4b8c2a6d9
Revises: c8a3f2e5b4d7
Create Date: 2026-06-01 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1f4b8c2a6d9"
down_revision: str | Sequence[str] | None = "c8a3f2e5b4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DROP COLUMN supprime aussi l'index partiel idx_sa_excluded.
    op.execute("ALTER TABLE source_authorships DROP COLUMN excluded")


def downgrade() -> None:
    op.execute("ALTER TABLE source_authorships ADD COLUMN excluded boolean NOT NULL DEFAULT false")
    op.execute(
        "CREATE INDEX idx_sa_excluded ON source_authorships (excluded) WHERE excluded = true"
    )
