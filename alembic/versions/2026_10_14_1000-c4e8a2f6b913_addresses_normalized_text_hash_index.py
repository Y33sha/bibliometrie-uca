"""Index hash sur le texte normalisé des adresses

`idx_addresses_normalized_text` sert les comparaisons d'égalité entre textes normalisés. Il accepte des valeurs de toute longueur.

Revision ID: c4e8a2f6b913
Revises: a9d2f4c6b718
Create Date: 2026-10-14 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8a2f6b913"
down_revision: str | Sequence[str] | None = "a9d2f4c6b718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DROP INDEX structures.idx_addresses_normalized_text;
        CREATE INDEX idx_addresses_normalized_text
            ON structures.addresses USING hash (normalized_text);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX structures.idx_addresses_normalized_text;
        CREATE INDEX idx_addresses_normalized_text
            ON structures.addresses USING btree (normalized_text);
    """)
