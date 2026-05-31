"""staging.disappeared_at : marquage des publications disparues de leur source

Phase « refresh stale » : une row dont `last_seen_at` est ancien est refetchée
par id natif ; si la source répond 404 (ou si elle est non-refetchable mais
re-moissonnée par le bulk et restée stale), on pose `disappeared_at = now()`.

Conservateur : on **marque seulement**. Aucune propagation/exclusion/suppression
en aval tant que des cas concrets n'ont pas été observés.

Revision ID: a7e3f1c9b5d2
Revises: f2a9c5b7d1e3
Create Date: 2026-05-31 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7e3f1c9b5d2"
down_revision: str | Sequence[str] | None = "f2a9c5b7d1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE staging ADD COLUMN disappeared_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE staging DROP COLUMN disappeared_at")
