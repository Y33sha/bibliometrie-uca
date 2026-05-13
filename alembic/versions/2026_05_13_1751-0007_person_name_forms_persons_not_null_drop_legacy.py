"""person_name_forms : persons NOT NULL + CHECK + GIN + drop legacy cols

Phase 6 (finale) du chantier `DATA_person-name-forms-normalisation.md`.
La MetaData et le code (writers Phase 4, readers Phase 5) sont déjà
alignés depuis le commit cf45a27 ; cette migration verrouille la
nouvelle colonne et droppe les anciennes :

- `persons` SET NOT NULL (toutes les rows sont peuplées depuis le
  backfill Phase 2 + writers Phase 4).
- CHECK `persons <> '{}'::jsonb` (rejet des rows orphelines —
  cleanup automatique côté code via DELETE quand `persons` devient
  vide).
- Index GIN `(persons jsonb_path_ops)` pour les queries
  `WHERE persons ? '<pid>'` (lookup admin "formes pour personne X").
- DROP `person_ids` (et son index GIN `idx_pnf_person_ids`).
- DROP `sources`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-13 17:51:50.562356
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("person_name_forms", "persons", nullable=False)
    op.create_check_constraint(
        "persons_not_empty",
        "person_name_forms",
        "persons <> '{}'::jsonb",
    )
    op.create_index(
        "idx_pnf_persons_gin",
        "person_name_forms",
        ["persons"],
        postgresql_using="gin",
        postgresql_ops={"persons": "jsonb_path_ops"},
    )
    op.drop_index("idx_pnf_person_ids", table_name="person_name_forms")
    op.drop_column("person_name_forms", "person_ids")
    op.drop_column("person_name_forms", "sources")


def downgrade() -> None:
    op.add_column(
        "person_name_forms",
        sa.Column("sources", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "person_name_forms",
        sa.Column("person_ids", postgresql.ARRAY(sa.Integer()), nullable=True),
    )
    op.create_index(
        "idx_pnf_person_ids",
        "person_name_forms",
        ["person_ids"],
        postgresql_using="gin",
    )
    op.drop_index("idx_pnf_persons_gin", table_name="person_name_forms")
    op.drop_constraint("persons_not_empty", "person_name_forms", type_="check")
    op.alter_column("person_name_forms", "persons", nullable=True)
