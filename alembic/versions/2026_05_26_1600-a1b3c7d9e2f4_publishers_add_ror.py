"""publishers : ajouter la colonne `ror`

Prépare la Phase 2 du chantier `pipeline-publishers-journals` : enrichissement des publishers depuis l'API OpenAlex Publishers. Le champ `ids.ror` retourné par OpenAlex est l'identifiant ROR canonique de l'éditeur, qui servira ensuite à dériver le `publisher_type` (Phase 3 — ROR `types` → notre enum).

Contrainte `UNIQUE` (NULLs distincts, comportement Postgres par défaut) : un même ROR non-NULL ne peut pas pointer vers deux publishers locaux. Aligné sur le `UNIQUE(openalex_id)` déjà en place.

Revision ID: a1b3c7d9e2f4
Revises: f4a7b2c8e1d3
Create Date: 2026-05-26 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b3c7d9e2f4"
down_revision: str | Sequence[str] | None = "f4a7b2c8e1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("publishers", sa.Column("ror", sa.Text(), nullable=True))
    op.create_unique_constraint("publishers_ror_key", "publishers", ["ror"])


def downgrade() -> None:
    op.drop_constraint("publishers_ror_key", "publishers", type_="unique")
    op.drop_column("publishers", "ror")
