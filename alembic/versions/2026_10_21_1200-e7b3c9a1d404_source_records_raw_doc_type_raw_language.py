"""Colonnes raw_doc_type et raw_language de source_records

Revision ID: e7b3c9a1d404
Revises: d2a6f9c3e815
Create Date: 2026-10-21 12:00:00.000000

`raw_doc_type` et `raw_language` gardent le type de document et la langue donnés par la source. `doc_type` et `language` reçoivent leur traduction dans le vocabulaire du référentiel. Le oneshot `interfaces/cli/oneshot/split_raw_doc_type_language.py` remplit les deux colonnes sur les données existantes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7b3c9a1d404"
down_revision: str | Sequence[str] | None = "d2a6f9c3e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENTS = {
    "raw_doc_type": "Type de document donné par la source, dans son vocabulaire.",
    "raw_language": "Langue donnée par la source, dans son vocabulaire.",
}


def upgrade() -> None:
    for column, comment in _COMMENTS.items():
        op.execute(f"ALTER TABLE sources.source_records ADD COLUMN {column} text")
        op.execute(f"COMMENT ON COLUMN sources.source_records.{column} IS '{comment}'")


def downgrade() -> None:
    for column in _COMMENTS:
        op.execute(f"ALTER TABLE sources.source_records DROP COLUMN {column}")
