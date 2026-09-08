"""Contraint la forme des valeurs de config dont la clé impose un type

Un plafond d'interrogation est un entier positif ou nul ; une année tombe entre
1970 et 2100. La colonne étant `jsonb`, toute valeur JSON y entrait, une chaîne
comprise. Les valeurs déjà hors forme sont ramenées avant la pose : les plafonds
à zéro (illimité), l'année à celle du seed.

Revision ID: b5d0f28c4a37
Revises: a4c9e17b3f26
Create Date: 2026-09-08 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5d0f28c4a37"
down_revision: str | Sequence[str] | None = "a4c9e17b3f26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAP_KEYS = "('unpaywall_max_per_run', 'fetch_missing_max_per_source')"
_YEAR_KEYS = "('pipeline_start_year_full')"


def upgrade() -> None:
    # Les valeurs hors forme, qu'aucune contrainte n'écartait, empêcheraient la pose.
    op.execute(
        f"UPDATE config SET value = '0'::jsonb "
        f"WHERE key IN {_CAP_KEYS} "
        f"  AND (jsonb_typeof(value) <> 'number' OR (value)::numeric < 0 "
        f"       OR (value)::numeric <> trunc((value)::numeric))"
    )
    op.execute(
        f"UPDATE config SET value = '2017'::jsonb "
        f"WHERE key IN {_YEAR_KEYS} "
        f"  AND (jsonb_typeof(value) <> 'number' OR (value)::numeric NOT BETWEEN 1970 AND 2100 "
        f"       OR (value)::numeric <> trunc((value)::numeric))"
    )
    op.execute(
        f"ALTER TABLE config ADD CONSTRAINT config_cap_is_non_negative_integer CHECK ("
        f"  key NOT IN {_CAP_KEYS}"
        f"  OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 0"
        f"      AND (value)::numeric = trunc((value)::numeric)))"
    )
    op.execute(
        f"ALTER TABLE config ADD CONSTRAINT config_year_is_in_range CHECK ("
        f"  key NOT IN {_YEAR_KEYS}"
        f"  OR (jsonb_typeof(value) = 'number' AND (value)::numeric BETWEEN 1970 AND 2100"
        f"      AND (value)::numeric = trunc((value)::numeric)))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE config DROP CONSTRAINT config_year_is_in_range")
    op.execute("ALTER TABLE config DROP CONSTRAINT config_cap_is_non_negative_integer")
