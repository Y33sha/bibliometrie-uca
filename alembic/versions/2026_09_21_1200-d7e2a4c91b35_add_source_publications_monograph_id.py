"""Rattache les enregistrements à leur monographie, et donne son ISBN électronique à la monographie

La normalisation pose `source_publications.monograph_id`, que l'agrégation reporte sur `publications.monograph_id`. `monographs.eisbn` porte l'ISBN de l'édition électronique, `monographs.isbn` celui de l'édition papier ou d'un support inconnu.

Revision ID: d7e2a4c91b35
Revises: a1c8e5b30f47
Create Date: 2026-09-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e2a4c91b35"
down_revision: str | Sequence[str] | None = "a1c8e5b30f47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("monographs", sa.Column("eisbn", sa.Text()))
    op.create_unique_constraint("monographs_eisbn_key", "monographs", ["eisbn"])

    op.add_column(
        "source_publications",
        sa.Column("monograph_id", sa.Integer(), sa.ForeignKey("monographs.id")),
    )
    op.create_index(
        "idx_source_publications_monograph",
        "source_publications",
        ["monograph_id"],
        postgresql_where=sa.text("monograph_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_source_publications_monograph", "source_publications")
    op.drop_column("source_publications", "monograph_id")
    op.drop_constraint("monographs_eisbn_key", "monographs")
    op.drop_column("monographs", "eisbn")
