"""drop notes columns : publishers, journals, publications, authorships

Champ `notes` jamais utilisé en pratique (vide partout en base), exposé dans
quelques modals admin qui sont retirés en parallèle. Suppression côté schéma
+ propagation Python (aggregates / repositories / DTOs / tests).

Le champ `apc_payments.remarks` est explicitement conservé : il vient d'un
import CSV et la convention est de tout préserver.

Revision ID: d9c4f1a7e3b2
Revises: b7d3e8f2c1a5
Create Date: 2026-05-21 16:53:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9c4f1a7e3b2"
down_revision: str | Sequence[str] | None = "b7d3e8f2c1a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE publishers DROP COLUMN notes")
    op.execute("ALTER TABLE journals DROP COLUMN notes")
    op.execute("ALTER TABLE publications DROP COLUMN notes")
    op.execute("ALTER TABLE authorships DROP COLUMN notes")


def downgrade() -> None:
    op.execute("ALTER TABLE authorships ADD COLUMN notes text")
    op.execute("ALTER TABLE publications ADD COLUMN notes text")
    op.execute("ALTER TABLE journals ADD COLUMN notes text")
    op.execute("ALTER TABLE publishers ADD COLUMN notes text")
