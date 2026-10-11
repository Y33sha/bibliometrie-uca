"""La suppression d'une personne supprime ses authorships

`authorships.person_id` est `NOT NULL` : la clé étrangère passe de `ON DELETE SET NULL` à `ON DELETE CASCADE`.

Revision ID: f4c9d6e2a137
Revises: e3b8c5d1f926
Create Date: 2026-10-11 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4c9d6e2a137"
down_revision: str | Sequence[str] | None = "e3b8c5d1f926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_fk(on_delete: str) -> None:
    op.execute(f"""
        ALTER TABLE authorships DROP CONSTRAINT authorships_person_id_fkey;
        ALTER TABLE authorships ADD CONSTRAINT authorships_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE {on_delete};
    """)


def upgrade() -> None:
    _set_fk("CASCADE")


def downgrade() -> None:
    _set_fk("SET NULL")
