"""Plafond de la phase fetch_stale

`fetch_stale_max_per_source` borne le nombre de documents non revus cherchés de nouveau par source à chaque run. Zéro vaut illimité, valeur par défaut. La contrainte des plafonds couvre la clé.

Revision ID: c3a7e1f94b20
Revises: f8dd2f2054a9
Create Date: 2026-11-23 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a7e1f94b20"
down_revision: str | Sequence[str] | None = "f8dd2f2054a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAP_KEYS = (
    "('doi_resolution_max_per_run', 'fetch_missing_max_per_source', 'sudoc_max_per_run', "
    "'unpaywall_max_per_run')"
)
_CAP_KEYS_WITH_FETCH_STALE = (
    "('doi_resolution_max_per_run', 'fetch_missing_max_per_source', "
    "'fetch_stale_max_per_source', 'sudoc_max_per_run', 'unpaywall_max_per_run')"
)


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
        "('fetch_stale_max_per_source', '0', "
        "'Nombre maximum de documents non revus cherchés de nouveau par source "
        "à la phase fetch_stale, par run. 0 = illimité.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint(_CAP_KEYS_WITH_FETCH_STALE))


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint(_CAP_KEYS))
    op.execute("DELETE FROM ops.config WHERE key = 'fetch_stale_max_per_source'")
