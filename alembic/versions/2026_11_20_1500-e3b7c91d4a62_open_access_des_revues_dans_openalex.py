"""Open access intégral des revues d'après OpenAlex

`serials` gagne `openalex_is_oa` et `openalex_oa_flip_year`, lus par le calcul du statut open access des publications. Les revues sont toutes à chercher de nouveau dans OpenAlex au run suivant, pour remplir ces colonnes.

Revision ID: e3b7c91d4a62
Revises: c5d8a1e3f276
Create Date: 2026-11-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3b7c91d4a62"
down_revision: str | Sequence[str] | None = "c5d8a1e3f276"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "serials",
        sa.Column(
            "openalex_is_oa",
            sa.Boolean(),
            comment="Revue en open access intégral d'après OpenAlex (`is_oa`). NULL : revue absente d'OpenAlex ou jamais cherchée.",
        ),
        schema="publishing",
    )
    op.add_column(
        "serials",
        sa.Column(
            "openalex_oa_flip_year",
            sa.SmallInteger(),
            comment="Année du passage de la revue à l'open access intégral d'après OpenAlex (`oa_flip_year`). NULL pour une revue née en open access intégral.",
        ),
        schema="publishing",
    )
    op.execute("UPDATE publishing.serials SET openalex_checked_at = NULL")


def downgrade() -> None:
    op.drop_column("serials", "openalex_oa_flip_year", schema="publishing")
    op.drop_column("serials", "openalex_is_oa", schema="publishing")
