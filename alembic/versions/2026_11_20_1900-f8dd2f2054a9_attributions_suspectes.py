"""Attributions suspectes

Table `persons.suspect_contributions` : contributions rattachées à une personne et probablement signées par un homonyme, recalculées à chaque run par la phase `suspect_attributions`. Type `suspect_reason` : motif du signalement.

Revision ID: f8dd2f2054a9
Revises: 7f2c4e9a1b85
Create Date: 2026-11-20 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from alembic import op

revision: str = "f8dd2f2054a9"
down_revision: str | Sequence[str] | None = "7f2c4e9a1b85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REASON = PgEnum("cluster", "rejected_publications", name="suspect_reason", create_type=False)


def upgrade() -> None:
    _REASON.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "suspect_contributions",
        sa.Column("contribution_id", sa.Integer, primary_key=True),
        sa.Column(
            "person_id",
            sa.Integer,
            nullable=False,
            comment="Personne rattachée à la contribution au moment du calcul.",
        ),
        sa.Column("reason", _REASON, nullable=False),
        sa.Column(
            "cluster",
            sa.SmallInteger,
            comment="Numéro du cluster signalé parmi ceux de la personne. NULL pour le motif `rejected_publications`.",
        ),
        sa.ForeignKeyConstraint(
            ["contribution_id"],
            ["publications.contributions.id"],
            name="suspect_contributions_contribution_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.persons.id"],
            name="suspect_contributions_person_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(cluster IS NULL) = (reason = 'rejected_publications')",
            name="suspect_contributions_cluster_by_reason",
        ),
        comment=(
            "Contributions rattachées à une personne et probablement signées par un homonyme : "
            "publication d'un cluster isolé (`cluster`), ou plus proche des publications rejetées "
            "pour la personne que de ses autres publications (`rejected_publications`). "
            "Recalculée à chaque run."
        ),
        schema="persons",
    )
    op.create_index(
        "suspect_contributions_person_id_idx",
        "suspect_contributions",
        ["person_id"],
        schema="persons",
    )


def downgrade() -> None:
    op.drop_table("suspect_contributions", schema="persons")
    _REASON.drop(op.get_bind(), checkfirst=False)
