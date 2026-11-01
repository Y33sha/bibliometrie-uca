"""ISSN-L lu dans la table de l'ISSN International Centre

Revision ID: e56b7ba228e7
Revises: 52b79a5bc3a2
Create Date: 2026-11-01 08:00:00.000000

`serial_issns.issnl` reçoit l'ISSN-L de la table de l'ISSN International Centre, et `issnl_checked_at` la date de son import. Les valeurs lues dans le Sudoc restent jusqu'au premier import. `issnl_table_refresh_after_days` donne, en jours, le délai avant de télécharger de nouveau la table, 30 par défaut.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e56b7ba228e7"
down_revision: str | Sequence[str] | None = "52b79a5bc3a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELAY_KEYS = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'fetch_stale_after_days', 'unpaywall_recheck_after_days')"
)
_DELAY_KEYS_WITH_ISSNL_TABLE = (
    "('doaj_refresh_after_days', 'doi_resolution_recheck_after_days', "
    "'fetch_missing_retry_after_days', 'fetch_stale_after_days', 'issnl_table_refresh_after_days', "
    "'unpaywall_recheck_after_days')"
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
        ALTER TABLE publishing.serial_issns ADD COLUMN issnl_checked_at timestamp with time zone;
        COMMENT ON COLUMN publishing.serial_issns.issnl IS
            'ISSN-L de l''ISSN d''après la table de l''ISSN International Centre. NULL : ISSN absent de la table au dernier import, ou ajouté depuis.';
        COMMENT ON COLUMN publishing.serial_issns.issnl_checked_at IS
            'Date du dernier import de la table ISSN-L qui a lu l''ISSN. NULL : jamais lu.';
    """)
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('issnl_table_refresh_after_days', '30', "
        "'Délai, en jours, avant de télécharger de nouveau la table ISSN-L de l''ISSN International Centre.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS_WITH_ISSNL_TABLE))


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_delay_is_positive_integer")
    op.execute(_delay_constraint(_DELAY_KEYS))
    op.execute("DELETE FROM ops.config WHERE key = 'issnl_table_refresh_after_days'")
    op.execute("""
        ALTER TABLE publishing.serial_issns DROP COLUMN issnl_checked_at;
        COMMENT ON COLUMN publishing.serial_issns.issnl IS
            'ISSN-L de l''ISSN d''après sa notice Sudoc. NULL : inconnu.';
    """)
