"""Droits de l'API pour la fusion manuelle de publications

Revision ID: b8f2d6e1c947
Revises: a7c3e9d2f514
Create Date: 2026-10-28 16:15:00.000000

Migration sans ordre propre. `alembic/env.py` réapplique `grants.sql` après toute migration jouée, donc chaque base reçoit les droits de l'API sur `manual_merges`, `manual_merge_source_records`, `contributions` et `aligned_source_contributions`.
"""

from collections.abc import Sequence

revision: str = "b8f2d6e1c947"
down_revision: str | Sequence[str] | None = "a7c3e9d2f514"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
