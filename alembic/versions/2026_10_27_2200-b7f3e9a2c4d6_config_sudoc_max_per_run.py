"""Plafond des revues vérifiées dans le Sudoc par run

`sudoc_max_per_run` borne le nombre de revues vérifiées dans le Sudoc à chaque run, 10 000 par défaut. Zéro vaut illimité. La contrainte des plafonds couvre la clé.

Revision ID: b7f3e9a2c4d6
Revises: e5b2d8f4a1c7
Create Date: 2026-10-27 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7f3e9a2c4d6"
down_revision: str | Sequence[str] | None = "e5b2d8f4a1c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cap_constraint(keys: str) -> str:
    return (
        "ALTER TABLE ops.config ADD CONSTRAINT config_cap_is_non_negative_integer CHECK ("
        f"  key NOT IN {keys}"
        "  OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 0"
        "      AND (value)::numeric = trunc((value)::numeric)))"
    )


def upgrade() -> None:
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('sudoc_max_per_run', '10000', "
        "'Nombre maximum de revues vérifiées dans le Sudoc par run. 0 = illimité.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(
        _cap_constraint(
            "('fetch_missing_max_per_source', 'sudoc_max_per_run', 'unpaywall_max_per_run')"
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint("('fetch_missing_max_per_source', 'unpaywall_max_per_run')"))
    op.execute("DELETE FROM ops.config WHERE key = 'sudoc_max_per_run'")
