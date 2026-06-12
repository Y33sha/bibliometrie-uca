"""place_name_forms : kind accepte 'city'

La passe de détection des lieux (anciennement « institution ») boucle désormais
sur les formes `kind IN ('institution', 'city')`. On élargit le CHECK pour
accueillir les villes (à seeder dans une marche ultérieure).

Revision ID: a4c7e2f9b6d1
Revises: f3a8d2c5e1b7
Create Date: 2026-06-12 09:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4c7e2f9b6d1"
down_revision: str | Sequence[str] | None = "f3a8d2c5e1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE place_name_forms DROP CONSTRAINT place_name_forms_kind_check")
    op.execute(
        "ALTER TABLE place_name_forms ADD CONSTRAINT place_name_forms_kind_check "
        "CHECK (kind IN ('country', 'institution', 'city'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE place_name_forms DROP CONSTRAINT place_name_forms_kind_check")
    op.execute(
        "ALTER TABLE place_name_forms ADD CONSTRAINT place_name_forms_kind_check "
        "CHECK (kind IN ('country', 'institution'))"
    )
