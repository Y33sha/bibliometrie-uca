"""File de normalisation de staging, à la place de staging.processed

La file `queues.staging_normalization_queue` contient les lignes de `staging` à normaliser, sur le modèle des autres files : un marquage reçoit un nouveau `seq`, et la normalisation supprime seulement les couples `(id, seq)` relevés. Une ligne réécrite pendant sa normalisation reste donc en file. La migration y met les lignes à traiter, hors documents tronqués : ceux-ci entrent en file à leur complément.

Revision ID: c41e8a7d93b2
Revises: 7b3e91c4a6d2
Create Date: 2026-11-03 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c41e8a7d93b2"
down_revision: str | Sequence[str] | None = "7b3e91c4a6d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENT = (
    "Documents moissonnés, en transit vers les tables sources. Une ligne à normaliser est "
    "dans queues.staging_normalization_queue ; la normalisation vide raw_data."
)
_PREVIOUS_COMMENT = (
    "Documents moissonnés, en transit vers les tables sources. Deux états : à traiter "
    "(processed FALSE, raw_data porte le payload de la source), normalisée (processed "
    "TRUE, raw_data vidé)."
)


def upgrade() -> None:
    op.create_table(
        "staging_normalization_queue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("seq", sa.BigInteger, sa.Identity(always=True), nullable=False),
        schema="queues",
    )
    op.execute("""
        INSERT INTO queues.staging_normalization_queue (id)
        SELECT id FROM sources.staging
        WHERE processed IS NOT TRUE AND NOT authors_truncated
    """)
    op.drop_index("idx_staging_processed", table_name="staging", schema="sources")
    op.drop_column("staging", "processed", schema="sources")
    op.create_table_comment("staging", _COMMENT, schema="sources")


def downgrade() -> None:
    op.add_column(
        "staging",
        sa.Column("processed", sa.Boolean, server_default=sa.false()),
        schema="sources",
    )
    op.execute("""
        UPDATE sources.staging s
        SET processed = NOT s.authors_truncated AND NOT EXISTS (
            SELECT 1 FROM queues.staging_normalization_queue q WHERE q.id = s.id
        )
    """)
    op.create_index(
        "idx_staging_processed",
        "staging",
        ["processed"],
        schema="sources",
        postgresql_where=sa.text("NOT processed"),
    )
    op.drop_table("staging_normalization_queue", schema="queues")
    op.create_table_comment("staging", _PREVIOUS_COMMENT, schema="sources")
