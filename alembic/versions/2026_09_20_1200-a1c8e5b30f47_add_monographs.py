"""Crée la table monographs

Une monographie est un livre ou un volume d'actes qui contient des publications de la base. Sa clé est technique : l'ISBN manque à beaucoup de monographies, et porte seulement une contrainte d'unicité. `publications.monograph_id` rattache une publication à la monographie qui la contient.

Revision ID: a1c8e5b30f47
Revises: c5a91e3d7b20
Create Date: 2026-09-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c8e5b30f47"
down_revision: str | Sequence[str] | None = "c5a91e3d7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monographs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text(), nullable=False),
        sa.Column("proceedings", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("year", sa.Integer()),
        sa.Column("isbn", sa.Text(), unique=True),
        sa.Column(
            "publisher_id", sa.Integer(), sa.ForeignKey("publishers.id", ondelete="SET NULL")
        ),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journals.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_monographs_title_normalized", "monographs", ["title_normalized"])
    op.create_index("idx_monographs_publisher", "monographs", ["publisher_id"])
    op.create_index("idx_monographs_journal", "monographs", ["journal_id"])
    op.execute(
        "COMMENT ON COLUMN public.monographs.proceedings IS "
        "'Vrai pour un volume d''actes de congrès, faux pour un livre.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.monographs.year IS "
        "'Année de publication. Elle classe les volumes d''actes d''un même congrès.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.monographs.journal_id IS "
        "'Collection dont la monographie fait partie, quand cette collection porte un ISSN.'"
    )

    op.add_column(
        "publications",
        sa.Column("monograph_id", sa.Integer(), sa.ForeignKey("monographs.id")),
    )
    op.create_index(
        "idx_publications_monograph",
        "publications",
        ["monograph_id"],
        postgresql_where=sa.text("monograph_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_publications_monograph", "publications")
    op.drop_column("publications", "monograph_id")
    op.drop_table("monographs")
