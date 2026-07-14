"""journals et publishers : suppression du flag is_predatory

`is_predatory` marque les revues et éditeurs prédateurs. La valeur reste à false sur tout le corpus et n'alimente aucun affichage, filtre ou calcul. On supprime les deux colonnes.

Revision ID: a3d7f1c9b524
Revises: f2a6c9d40e13
Create Date: 2026-07-14 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3d7f1c9b524"
down_revision: str | Sequence[str] | None = "f2a6c9d40e13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.journals DROP COLUMN is_predatory;")
    op.execute("ALTER TABLE public.publishers DROP COLUMN is_predatory;")


def downgrade() -> None:
    op.execute("ALTER TABLE public.publishers ADD COLUMN is_predatory boolean DEFAULT false;")
    op.execute("ALTER TABLE public.journals ADD COLUMN is_predatory boolean DEFAULT false;")
