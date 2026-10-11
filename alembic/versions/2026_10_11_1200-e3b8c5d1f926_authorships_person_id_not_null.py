"""Une authorship a toujours une personne

Une authorship est le lien d'une publication à une personne : `authorships.person_id` devient `NOT NULL`. Les lignes sans personne, qu'aucun chemin d'écriture ne produit, sont supprimées d'abord.

Revision ID: e3b8c5d1f926
Revises: d2a7f4c9e815
Create Date: 2026-10-11 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3b8c5d1f926"
down_revision: str | Sequence[str] | None = "d2a7f4c9e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM authorships WHERE person_id IS NULL")
    op.execute("ALTER TABLE authorships ALTER COLUMN person_id SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE authorships ALTER COLUMN person_id DROP NOT NULL")
