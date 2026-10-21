"""Colonne raw_metadata de source_records renommée corrections

Revision ID: f3c8d2a6b517
Revises: e7b3c9a1d404
Create Date: 2026-10-21 14:00:00.000000

La colonne garde, pour chaque champ corrigé par une règle, la valeur d'avant correction et la règle.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3c8d2a6b517"
down_revision: str | Sequence[str] | None = "e7b3c9a1d404"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources.source_records RENAME COLUMN raw_metadata TO corrections")
    op.execute(
        "ALTER TABLE sources.source_records RENAME CONSTRAINT source_records_raw_metadata_is_object"
        " TO source_records_corrections_is_object"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sources.source_records RENAME CONSTRAINT source_records_corrections_is_object"
        " TO source_records_raw_metadata_is_object"
    )
    op.execute("ALTER TABLE sources.source_records RENAME COLUMN corrections TO raw_metadata")
