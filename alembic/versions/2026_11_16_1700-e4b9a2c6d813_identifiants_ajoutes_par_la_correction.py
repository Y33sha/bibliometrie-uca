"""Identifiants ajoutés par la correction

La colonne `source_record_identifiers.added_by` nomme la règle de correction qui ajoute un identifiant. Un document qui porte le DOI d'un erratum Crossref reçoit le DOI de l'article corrigé (`AVIS_VS_ARTICLE`).

Revision ID: e4b9a2c6d813
Revises: c7e3a91f5b24
Create Date: 2026-11-16 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4b9a2c6d813"
down_revision: str | Sequence[str] | None = "c7e3a91f5b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENT = "Règle de correction qui ajoute l'identifiant. NULL : identifiant donné par la source."


def upgrade() -> None:
    op.add_column(
        "source_record_identifiers",
        sa.Column("added_by", sa.Text(), comment=_COMMENT),
        schema="sources",
    )


def downgrade() -> None:
    op.drop_column("source_record_identifiers", "added_by", schema="sources")
