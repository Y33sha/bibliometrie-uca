"""Droit de l'API sur les statuts des identifiants des enregistrements sources

Revision ID: e2b8f4c6a913
Revises: a4d7c1e9b2f6
Create Date: 2026-10-29 17:00:00.000000

Migration sans ordre propre. `alembic/env.py` réapplique `grants.sql` après toute migration jouée, donc chaque base reçoit le droit `UPDATE` de l'API sur `source_record_identifiers`. Le changement de type d'une revue rejoue la correction unaire, qui écrit les statuts des identifiants.
"""

from collections.abc import Sequence

revision: str = "e2b8f4c6a913"
down_revision: str | Sequence[str] | None = "a4d7c1e9b2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
