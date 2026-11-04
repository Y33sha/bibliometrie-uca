"""Relecture des revues dans OpenAlex

Revision ID: 56f3892a5450
Revises: f3e332c91c33
Create Date: 2026-11-04 19:47:04.572824

`serials.openalex_checked_at` reçoit la date de la dernière lecture de la revue dans OpenAlex. `serial_openalex_recheck_after_days` donne, en jours, le délai avant de relire une revue, 7 par défaut.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "56f3892a5450"
down_revision: str | Sequence[str] | None = "f3e332c91c33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELAY_KEYS = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'fetch_stale_after_days', 'issnl_table_refresh_after_days', "
    "'unpaywall_recheck_after_days')"
)
_DELAY_KEYS_WITH_SERIAL_OPENALEX = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'fetch_stale_after_days', 'issnl_table_refresh_after_days', "
    "'serial_openalex_recheck_after_days', 'unpaywall_recheck_after_days')"
)


def _delay_constraint(keys: str) -> str:
    return (
        "ALTER TABLE ops.config ADD CONSTRAINT config_delay_is_positive_integer CHECK ("
        f"  key NOT IN {keys}"
        "  OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 1"
        "      AND (value)::numeric = trunc((value)::numeric)))"
    )


def upgrade() -> None:
    op.execute("""
        ALTER TABLE publishing.serials ADD COLUMN openalex_checked_at timestamp with time zone;
        COMMENT ON COLUMN publishing.serials.openalex_checked_at IS
            'Date de la dernière lecture de la revue dans OpenAlex. NULL : jamais lue.';
    """)
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('serial_openalex_recheck_after_days', '7', "
        "'Délai, en jours, avant de relire une revue dans OpenAlex : source, type et listes.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS_WITH_SERIAL_OPENALEX))


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS))
    op.execute("DELETE FROM ops.config WHERE key = 'serial_openalex_recheck_after_days'")
    op.execute("ALTER TABLE publishing.serials DROP COLUMN openalex_checked_at")
