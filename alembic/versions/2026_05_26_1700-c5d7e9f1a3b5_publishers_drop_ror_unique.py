"""publishers : retirer la contrainte UNIQUE sur `ror`

À l'usage, OpenAlex Publishers attribue parfois le même ROR à plusieurs entités OpenAlex distinctes — soit cas hiérarchique (parent + imprints), soit entités IRL effectivement distinctes (ex. `CNRS Editions` et `CNRS` partagent le ROR du `CNRS` côté OpenAlex alors que `CNRS Editions` est une entité d'édition distincte qu'on veut garder séparée localement).

Conséquence : la contrainte UNIQUE(ror) bloquait des écritures légitimes lors de l'enrichissement Phase 2. Le partage de ROR entre publishers locaux n'est pas un signal fiable de doublon — il sera diagnostiqué tranquillement au chantier de dédoublonnage publishers à venir (avec d'autres signaux : préfixes DOI, noms normalisés, openalex hierarchy).

Revision ID: c5d7e9f1a3b5
Revises: a1b3c7d9e2f4
Create Date: 2026-05-26 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5d7e9f1a3b5"
down_revision: str | Sequence[str] | None = "a1b3c7d9e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("publishers_ror_key", "publishers", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("publishers_ror_key", "publishers", ["ror"])
