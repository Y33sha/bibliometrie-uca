"""Ajoute la valeur 'media' à l'enum publisher_type

Un éditeur de presse (The Conversation Media Group) dépose des DOI pour ses articles. La correction de métadonnées type en `media` les documents dont le DOI appartient à un déposant de ce type.

Revision ID: e2b7f4c8a913
Revises: a8d3c6f19b42
Create Date: 2026-09-19 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2b7f4c8a913"
down_revision: str | Sequence[str] | None = "a8d3c6f19b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE publisher_type ADD VALUE IF NOT EXISTS 'media' BEFORE 'unknown'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade recrée le type sans
    # 'media' : les éditeurs qui le portent sont d'abord ramenés à 'unknown'.
    op.execute("UPDATE publishers SET publisher_type = 'unknown' WHERE publisher_type = 'media'")
    op.execute("ALTER TYPE publisher_type RENAME TO publisher_type_old")
    op.execute(
        "CREATE TYPE publisher_type AS ENUM "
        "('commercial', 'learned_society', 'academic_institution', 'repository', 'aggregator', "
        "'unknown')"
    )
    op.execute(
        "ALTER TABLE publishers ALTER COLUMN publisher_type DROP DEFAULT, "
        "ALTER COLUMN publisher_type TYPE publisher_type "
        "USING publisher_type::text::publisher_type, "
        "ALTER COLUMN publisher_type SET DEFAULT 'unknown'"
    )
    op.execute("DROP TYPE publisher_type_old")
