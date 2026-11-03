"""Retire la licence brute des champs propres aux sources

Les clés `license` (Crossref, OpenAlex, ScanR) et `licence` (HAL) quittent `source_extras`, dans les enregistrements sources et dans les publications. La licence normalisée de l'enregistrement source et de ses localisations sert seule. Un `source_extras` vidé devient NULL.

Revision ID: a6e3c1f8b2d4
Revises: f3b8d1a6c925
Create Date: 2026-11-03 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a6e3c1f8b2d4"
down_revision: str | Sequence[str] | None = "f3b8d1a6c925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("sources.source_records", "publications.publications")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"""
            UPDATE {table}
            SET source_extras = NULLIF(source_extras - 'license' - 'licence', '{{}}'::jsonb)
            WHERE source_extras ?| ARRAY['license', 'licence']
        """)


def downgrade() -> None:
    # Les licences brutes retirées sont perdues : le downgrade laisse les données en l'état.
    pass
