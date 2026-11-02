"""Année de début du moissonnage non fixée

Revision ID: 3f9c2d7a1e84
Revises: bd1b33b622f8
Create Date: 2026-11-02 12:00:00.000000

`pipeline_start_year_full` accepte le `null` JSON : sans année fixée, la première année moissonnée précède l'année courante de cinq ans. Une année déjà fixée reste en place. La migration pose la clé, à `null`, si elle est absente.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3f9c2d7a1e84"
down_revision: str | Sequence[str] | None = "bd1b33b622f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_YEAR_IN_RANGE = (
    "jsonb_typeof(value) = 'number' AND (value)::numeric BETWEEN 1970 AND 2100"
    " AND (value)::numeric = trunc((value)::numeric)"
)
_DESCRIPTION = "Première année moissonnée (incluse). Vide : cinq ans avant l''année courante."
_PREVIOUS_DESCRIPTION = (
    "Mode full/monthly : extraire depuis cette année (incluse) jusqu''à l''année courante."
    " Année absolue (ancre fixe), pas un offset — rétention cumulative."
)


def upgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_year_is_in_range")
    op.execute(
        "ALTER TABLE ops.config ADD CONSTRAINT config_year_is_in_range CHECK ("
        "key <> 'pipeline_start_year_full' OR jsonb_typeof(value) = 'null'"
        f" OR ({_YEAR_IN_RANGE}))"
    )
    op.execute(
        "INSERT INTO ops.config (key, value, description) "
        f"VALUES ('pipeline_start_year_full', 'null', '{_DESCRIPTION}') "
        "ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ops.config SET value = to_jsonb(extract(year FROM now())::int - 5)"
        " WHERE key = 'pipeline_start_year_full' AND value = 'null'::jsonb"
    )
    op.execute(
        f"UPDATE ops.config SET description = '{_PREVIOUS_DESCRIPTION}'"
        " WHERE key = 'pipeline_start_year_full'"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_year_is_in_range")
    op.execute(
        "ALTER TABLE ops.config ADD CONSTRAINT config_year_is_in_range CHECK ("
        f"key <> 'pipeline_start_year_full' OR ({_YEAR_IN_RANGE}))"
    )
