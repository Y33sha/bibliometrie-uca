"""Réglages de la lecture des adresses enregistrées des DOI chez doi.org

`doi_resolution_max_per_run` borne le nombre de DOI lus à chaque run, 10 000 par défaut. Zéro vaut illimité. `doi_resolution_recheck_after_days` donne, en jours, le délai avant de relire un DOI, 180 par défaut. Les contraintes des plafonds et des délais couvrent les deux clés.

Revision ID: 90ef8325f52b
Revises: 9662296ecd54
Create Date: 2026-10-31 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "90ef8325f52b"
down_revision: str | Sequence[str] | None = "9662296ecd54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAP_KEYS = "('fetch_missing_max_per_source', 'sudoc_max_per_run', 'unpaywall_max_per_run')"
_CAP_KEYS_WITH_RESOLUTION = (
    "('doi_resolution_max_per_run', 'fetch_missing_max_per_source', 'sudoc_max_per_run', "
    "'unpaywall_max_per_run')"
)
_DELAY_KEYS = (
    "('doaj_refresh_after_days', 'fetch_missing_retry_after_days', 'fetch_stale_after_days', "
    "'unpaywall_recheck_after_days')"
)
_DELAY_KEYS_WITH_RESOLUTION = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'fetch_stale_after_days', 'unpaywall_recheck_after_days')"
)


def _cap_constraint(keys: str) -> str:
    return (
        "ALTER TABLE ops.config ADD CONSTRAINT config_cap_is_non_negative_integer CHECK ("
        f"  key NOT IN {keys}"
        "  OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 0"
        "      AND (value)::numeric = trunc((value)::numeric)))"
    )


def _delay_constraint(keys: str) -> str:
    return (
        "ALTER TABLE ops.config ADD CONSTRAINT config_delay_is_positive_integer CHECK ("
        f"  key NOT IN {keys}"
        "  OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 1"
        "      AND (value)::numeric = trunc((value)::numeric)))"
    )


def upgrade() -> None:
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('doi_resolution_max_per_run', '10000', "
        "'Nombre maximum de DOI dont l''adresse enregistrée est lue chez doi.org par run. "
        "0 = illimité.'), "
        "('doi_resolution_recheck_after_days', '180', "
        "'Délai, en jours, avant de relire chez doi.org l''adresse enregistrée d''un DOI.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint(_CAP_KEYS_WITH_RESOLUTION))
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS_WITH_RESOLUTION))


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint(_CAP_KEYS))
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS))
    op.execute(
        "DELETE FROM ops.config"
        " WHERE key IN ('doi_resolution_max_per_run', 'doi_resolution_recheck_after_days')"
    )
