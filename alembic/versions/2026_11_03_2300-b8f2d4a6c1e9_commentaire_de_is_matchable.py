"""Commentaire de source_records.is_matchable réduit à sa définition

Les cas d'exclusion sont décrits par la fonction qui calcule la colonne.

Revision ID: b8f2d4a6c1e9
Revises: a6e3c1f8b2d4
Create Date: 2026-11-03 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8f2d4a6c1e9"
down_revision: str | Sequence[str] | None = "a6e3c1f8b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "COMMENT ON COLUMN sources.source_records.is_matchable IS "
        "'Faux pour un enregistrement source écarté de la réconciliation.'"
    )


def downgrade() -> None:
    op.execute(
        "COMMENT ON COLUMN sources.source_records.is_matchable IS "
        "'Faux pour un enregistrement source écarté de la réconciliation : préfixe DOI exclu, "
        "titre de paratexte, enregistrement ScanR issu d''un dépôt HAL introuvable, "
        "enregistrement d''agrégateur sans DOI, lien ni clé de confirmation.'"
    )
