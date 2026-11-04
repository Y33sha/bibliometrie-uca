"""Textes de la recherche des métadonnées des revues

Revision ID: 90d4bdd8877d
Revises: bfa6bd127150
Create Date: 2026-11-04 20:34:18.339301

Commentaire de `serials.openalex_checked_at` et description de `serial_openalex_recheck_after_days`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "90d4bdd8877d"
down_revision: str | Sequence[str] | None = "bfa6bd127150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN publishing.serials.openalex_checked_at IS
            'Date de la dernière recherche des métadonnées de la revue dans OpenAlex. NULL : jamais cherchées.';
        UPDATE ops.config
        SET description = 'Délai, en jours, avant de chercher de nouveau les métadonnées d''une revue dans OpenAlex.'
        WHERE key = 'serial_openalex_recheck_after_days';
    """)


def downgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN publishing.serials.openalex_checked_at IS
            'Date de la dernière lecture de la revue dans OpenAlex. NULL : jamais lue.';
        UPDATE ops.config
        SET description = 'Délai, en jours, avant de relire une revue dans OpenAlex : source, type et listes.'
        WHERE key = 'serial_openalex_recheck_after_days';
    """)
