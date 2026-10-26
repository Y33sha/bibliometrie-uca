"""Ajout de publications.best_copy_url

Revision ID: e2b7c5a9d416
Revises: c4a8e1f6d293
Create Date: 2026-10-26 19:00:00.000000

Adresse de la meilleure copie ouverte d'une publication, calculée à la consolidation de la publication. Les listes de publications la lisent sans parcourir les localisations. Le script `interfaces.cli.oneshot.backfill_best_copy_urls` remplit le stock.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2b7c5a9d416"
down_revision: str | Sequence[str] | None = "c4a8e1f6d293"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE publications.publications ADD COLUMN best_copy_url text")
    op.execute(
        "COMMENT ON COLUMN publications.publications.best_copy_url IS "
        "'Adresse de la meilleure copie ouverte, parmi les localisations des enregistrements sources.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE publications.publications DROP COLUMN best_copy_url")
