"""drop person_name_forms.person_ids not null

Préparatif Phase 4 du chantier `DATA_person-name-forms-normalisation.md` :
la Phase 4 bascule les writers sur la colonne `persons` JSONB ; ils
n'écrivent plus dans `person_ids` ni `sources`. Le NOT NULL sur
`person_ids` doit donc tomber pour autoriser les nouveaux INSERT à
laisser la colonne NULL. La colonne elle-même (et `sources`) reste en
place jusqu'à la migration finale Phase 6 où elles sont DROP.

`sources` n'a déjà pas de NOT NULL — rien à faire de ce côté.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-13 17:15:24.544727
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("person_name_forms", "person_ids", nullable=True)


def downgrade() -> None:
    op.alter_column("person_name_forms", "person_ids", nullable=False)
