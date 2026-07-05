"""Ajoute la valeur 'admin' à l'enum structure_type

Type de structure administrative : service (direction des systèmes d'information,
bibliothèque universitaire) ou structure fédérative intermédiaire (institut, sous
tutelle de l'université et tutelle de laboratoires). Attribut descriptif : sans
incidence sur le périmètre ni le matching.

Revision ID: d3f8a1c05e47
Revises: b2f5c9d8a41e
Create Date: 2026-07-05 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3f8a1c05e47"
down_revision: str | Sequence[str] | None = "b2f5c9d8a41e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE structure_type ADD VALUE IF NOT EXISTS 'admin'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'un enum : on recrée le type sans 'admin'.
    # Les structures éventuellement typées 'admin' retombent sur 'autre'.
    op.execute("UPDATE structures SET structure_type = 'autre' WHERE structure_type = 'admin'")
    op.execute("ALTER TYPE structure_type RENAME TO structure_type_old")
    op.execute("""
        CREATE TYPE structure_type AS ENUM (
            'universite', 'chu', 'ecole', 'labo', 'equipe', 'site', 'autre', 'onr'
        )
    """)
    op.execute("""
        ALTER TABLE structures
        ALTER COLUMN structure_type TYPE structure_type
        USING structure_type::text::structure_type
    """)
    op.execute("DROP TYPE structure_type_old")
