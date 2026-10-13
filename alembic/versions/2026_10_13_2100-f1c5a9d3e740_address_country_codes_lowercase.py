"""Codes pays des adresses en minuscules, sans valeur hors code

ScanR transmet des codes en majuscules et des valeurs comme « -- ». Chaque code de `addresses.countries` passe en minuscules, les valeurs qui ne sont pas un code à deux lettres disparaissent, et les doublons sont fusionnés. Les adresses corrigées sont marquées `countries_dirty` : le run suivant recalcule les pays de leurs notices et de leurs publications.

Revision ID: f1c5a9d3e740
Revises: e3b7d1f5a926
Create Date: 2026-10-13 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c5a9d3e740"
down_revision: str | Sequence[str] | None = "e3b7d1f5a926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        WITH fixed AS (
            SELECT a.id,
                   (SELECT array_agg(DISTINCT lower(c) ORDER BY lower(c))
                    FROM unnest(a.countries) c
                    WHERE lower(c) ~ '^[a-z]{2}$')::char(2)[] AS countries
            FROM structures.addresses a
            WHERE EXISTS (SELECT 1 FROM unnest(a.countries) c WHERE c !~ '^[a-z]{2}$')
        )
        UPDATE structures.addresses a
        SET countries = fixed.countries, countries_dirty = true
        FROM fixed
        WHERE a.id = fixed.id
    """)


def downgrade() -> None:
    """Les codes d'origine sont perdus : la correction est sans retour."""
