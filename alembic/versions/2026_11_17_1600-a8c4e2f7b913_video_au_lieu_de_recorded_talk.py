"""Renomme la valeur 'recorded_talk' de l'enum doc_type en 'video'

HAL `VIDEO` et DataCite `Audiovisual` désignent toute vidéo : conférence filmée, film, vidéo de corpus. Le type d'avant correction, conservé dans `source_records.corrections`, suit le renommage.

Revision ID: a8c4e2f7b913
Revises: e4b9a2c6d813
Create Date: 2026-11-17 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8c4e2f7b913"
down_revision: str | Sequence[str] | None = "e4b9a2c6d813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(old: str, new: str) -> None:
    op.execute(f"ALTER TYPE doc_type RENAME VALUE '{old}' TO '{new}'")
    op.execute(f"""
        UPDATE sources.source_records
        SET corrections = jsonb_set(corrections, '{{doc_type,raw}}', '"{new}"')
        WHERE corrections->'doc_type'->>'raw' = '{old}'
    """)


def upgrade() -> None:
    _rename("recorded_talk", "video")


def downgrade() -> None:
    _rename("video", "recorded_talk")
