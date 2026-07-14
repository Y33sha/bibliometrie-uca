"""publishers : suppression de la colonne ror

`publishers.ror` est un identifiant ROR renseigné à titre d'affichage, dépourvu de tout lecteur (calcul, vue, projection API). On supprime la colonne.

Revision ID: f2a6c9d40e13
Revises: e5c9a1f3b207
Create Date: 2026-07-14 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2a6c9d40e13"
down_revision: str | Sequence[str] | None = "e5c9a1f3b207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.publishers DROP COLUMN ror;")


def downgrade() -> None:
    op.execute("ALTER TABLE public.publishers ADD COLUMN ror text;")
