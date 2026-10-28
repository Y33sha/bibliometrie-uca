"""Définition du rôle dérivé dans le commentaire de `source_record_identifiers.role`

Revision ID: d7b2f4a9c1e3
Revises: a1d103de75ef
Create Date: 2026-10-28 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7b2f4a9c1e3"
down_revision: str | Sequence[str] | None = "a1d103de75ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN sources.source_record_identifiers.role IS
            'primary : identifiant de l''enregistrement dans la source. derived : identifiant de l''enregistrement d''une autre source dont l''enregistrement source est dérivé. Un enregistrement source a au plus un identifiant dérivé. secondary : identifiant que la source attribue au même document. related : identifiant d''un document lié.';
    """)


def downgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN sources.source_record_identifiers.role IS
            'primary : identifiant de l''enregistrement dans la source. derived : identifiant de l''enregistrement d''une autre source dont la source tire le sien. secondary : identifiant que la source attribue au même document. related : identifiant d''un document lié.';
    """)
