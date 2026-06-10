"""addresses : suppression de la colonne resolved_at

La résolution des affiliations est désormais un recalcul complet idempotent à
chaque run (plus de mode incrémental « daily »). Le flag `resolved_at`, qui ne
servait qu'à filtrer les adresses non encore résolues, n'a plus d'usage : il
était relu uniquement comme `IS NULL` et le réécrire sur les ~800k lignes à
chaque run coûtait cher (maintenance d'index sur une table fortement indexée).

Revision ID: f8a2d6c1b9e3
Revises: e2c7a9f4b1d6
Create Date: 2026-06-10 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f8a2d6c1b9e3"
down_revision: str | Sequence[str] | None = "e2c7a9f4b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE addresses DROP COLUMN resolved_at")


def downgrade() -> None:
    op.execute("ALTER TABLE addresses ADD COLUMN resolved_at timestamp with time zone")
