"""journals : ajout doaj_payload (jsonb) + doaj_imported_at (timestamptz)

Stocke le payload DOAJ brut (extraction des champs utiles au fil des
besoins) et la date du dernier import. Permet de requêter les rows
stale et de re-synchroniser périodiquement.

Cible Phase 3 du chantier publishers-journals.

Revision ID: e5a3f7b8c2d4
Revises: d9c4f1a7e3b2
Create Date: 2026-05-21 17:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a3f7b8c2d4"
down_revision: str | Sequence[str] | None = "d9c4f1a7e3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE journals ADD COLUMN doaj_payload jsonb")
    op.execute("ALTER TABLE journals ADD COLUMN doaj_imported_at timestamp with time zone")


def downgrade() -> None:
    op.execute("ALTER TABLE journals DROP COLUMN doaj_imported_at")
    op.execute("ALTER TABLE journals DROP COLUMN doaj_payload")
