"""index fonctionnels nnt / hal_id sur source_publications.external_ids

`find_by_nnt` et `find_by_hal_id` (phase publications, `match_or_create`) cherchent
via `external_ids->>'nnt'` / `external_ids->>'hal_id'`. L'index GIN existant sur
`external_ids` ne sert pas l'opérateur `->>` (il ne répond qu'à `@>`/`?`), et le
planner se rabat sur un seq scan de `source_publications` (~483k lignes, ~0,38 s) à
chaque orphelin → Phase A en heures.

Index btree fonctionnels (partiels : l'égalité `= valeur` implique NOT NULL, donc
pleinement utilisables tout en restant petits). Validé par EXPLAIN ANALYZE :
seq scan 377 ms → index scan 0,13 ms.

Revision ID: a1b2c3d4e5f6
Revises: c4f8a1e6b3d9
Create Date: 2026-06-06 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c4f8a1e6b3d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_source_pubs_nnt "
        "ON public.source_publications ((external_ids->>'nnt')) "
        "WHERE (external_ids->>'nnt') IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_source_pubs_hal_id "
        "ON public.source_publications ((external_ids->>'hal_id')) "
        "WHERE (external_ids->>'hal_id') IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_source_pubs_hal_id")
    op.execute("DROP INDEX IF EXISTS idx_source_pubs_nnt")
