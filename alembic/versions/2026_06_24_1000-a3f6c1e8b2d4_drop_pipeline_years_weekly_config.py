"""config : suppression de pipeline_years_weekly (mode weekly retiré)

Le pipeline n'a plus que deux modes : `daily` (HAL incrémental) et `full` (plage
`[start_year … courante]`, `start_year` = `--start-year` ou config
`pipeline_start_year_full`). Le mode `weekly` et son offset `pipeline_years_weekly`
disparaissent.

Revision ID: a3f6c1e8b2d4
Revises: e2b7d4f1a9c6
Create Date: 2026-06-24 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3f6c1e8b2d4"
down_revision: str | Sequence[str] | None = "e2b7d4f1a9c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM config WHERE key = 'pipeline_years_weekly'")


def downgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value, description) "
        "VALUES ('pipeline_years_weekly', '1', 'Mode weekly : extraire depuis (annee courante - N)') "
        "ON CONFLICT (key) DO NOTHING"
    )
