"""source_authorships : drop des colonnes write-only source_structures et source_data

Les deux colonnes étaient peuplées au normalize mais jamais relues par le runtime (le
seul lecteur était le seed one-time `seed_place_names_from_hal`). Elles sont
re-dérivables des payloads bruts conservés dans le raw_store, donc supprimées pour
alléger `source_authorships` (~1,7 Go pour `source_structures`) et tous les scans de la
table (colonnes inline traînées par chaque seq scan).

Revision ID: e2b7d4f1a9c6
Revises: b4d1f7a2e9c3
Create Date: 2026-06-23 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2b7d4f1a9c6"
down_revision: str | Sequence[str] | None = "b4d1f7a2e9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE source_authorships DROP COLUMN source_structures")
    op.execute("ALTER TABLE source_authorships DROP COLUMN source_data")


def downgrade() -> None:
    op.execute("ALTER TABLE source_authorships ADD COLUMN source_structures text[]")
    op.execute("ALTER TABLE source_authorships ADD COLUMN source_data jsonb")
