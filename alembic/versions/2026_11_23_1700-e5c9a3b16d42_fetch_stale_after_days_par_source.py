"""Délai de fetch_stale par source

`fetch_stale_after_days` devient un objet `{source: jours}`. Chaque source reçoit le délai déjà en place. La contrainte des délais entiers exclut la clé. Une contrainte impose un objet.

Revision ID: e5c9a3b16d42
Revises: c3a7e1f94b20
Create Date: 2026-11-23 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5c9a3b16d42"
down_revision: str | Sequence[str] | None = "c3a7e1f94b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCES = ("hal", "openalex", "wos", "scanr", "ops", "theses", "crossref", "datacite", "inspire")

_DELAY_KEYS = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'fetch_stale_after_days', 'issnl_table_refresh_after_days', "
    "'serial_openalex_recheck_after_days', 'unpaywall_recheck_after_days')"
)
_DELAY_KEYS_WITHOUT_FETCH_STALE = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'issnl_table_refresh_after_days', "
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
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS_WITHOUT_FETCH_STALE))
    pairs = ", ".join(f"'{source}', value" for source in _SOURCES)
    op.execute(
        f"UPDATE ops.config SET value = jsonb_build_object({pairs}), "
        "description = 'Délai, en jours, au-delà duquel un document non revu est interrogé "
        "de nouveau à sa source, par source.' "
        "WHERE key = 'fetch_stale_after_days' AND jsonb_typeof(value) = 'number'"
    )
    op.execute(
        "ALTER TABLE ops.config ADD CONSTRAINT config_delay_by_source_is_object CHECK ("
        "  key NOT IN ('fetch_stale_after_days') OR jsonb_typeof(value) = 'object')"
    )


def downgrade() -> None:
    """La clé reprend le plus court des délais par source."""
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_by_source_is_object")
    op.execute(
        "UPDATE ops.config SET value = (SELECT to_jsonb(min(v::int)) FROM jsonb_each_text(value) AS e(k, v)), "
        "description = 'Délai, en jours, au-delà duquel un document non revu est interrogé "
        "de nouveau à sa source.' "
        "WHERE key = 'fetch_stale_after_days'"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS))
