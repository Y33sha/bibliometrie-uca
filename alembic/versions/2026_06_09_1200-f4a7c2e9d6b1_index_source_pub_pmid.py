"""index fonctionnel pmid sur source_publications.external_ids

`find_by_pmid` et `bulk_link_orphans_by_pmid` (phase publications, `match_or_create`)
cherchent via `external_ids->>'pmid'`. Comme pour nnt / hal_id (cf.
`a1b2c3d4e5f6`), l'index GIN sur `external_ids` ne sert pas l'opérateur `->>` et
le planner se rabat sur un seq scan de `source_publications` à chaque orphelin.

Index btree fonctionnel (partiel : l'égalité `= valeur` implique NOT NULL, donc
pleinement utilisable tout en restant petit).

Revision ID: f4a7c2e9d6b1
Revises: e3f5a7c9d1b4
Create Date: 2026-06-09 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4a7c2e9d6b1"
down_revision: str | Sequence[str] | None = "e3f5a7c9d1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_source_pubs_pmid "
        "ON public.source_publications ((external_ids->>'pmid')) "
        "WHERE (external_ids->>'pmid') IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_source_pubs_pmid")
