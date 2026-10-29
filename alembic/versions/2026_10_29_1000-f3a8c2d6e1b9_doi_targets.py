"""Cible du DOI d'une forme secondaire

Revision ID: f3a8c2d6e1b9
Revises: b2e7c4a1f8d6
Create Date: 2026-10-29 10:00:00.000000

`doi_targets` relie le DOI d'une version, d'une variante ou d'une pièce de dataset au DOI de l'œuvre principale présente en base.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a8c2d6e1b9"
down_revision: str | Sequence[str] | None = "b2e7c4a1f8d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sources.doi_targets (
            doi text PRIMARY KEY,
            target_doi text NOT NULL,
            rule text NOT NULL
        );
        CREATE INDEX idx_doi_targets_target_doi ON sources.doi_targets (target_doi);
        COMMENT ON TABLE sources.doi_targets IS
            'Cible du DOI d''une forme secondaire, réécrite par la correction par DOI partagé. La cible tient lieu du DOI pour la réconciliation et la consolidation.';
        COMMENT ON COLUMN sources.doi_targets.doi IS
            'DOI d''une version, d''une variante ou d''une pièce de dataset.';
        COMMENT ON COLUMN sources.doi_targets.target_doi IS
            'DOI de l''œuvre principale, présent en base.';
        COMMENT ON COLUMN sources.doi_targets.rule IS
            'Règle de correction qui relie les deux DOI.';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE sources.doi_targets;")
