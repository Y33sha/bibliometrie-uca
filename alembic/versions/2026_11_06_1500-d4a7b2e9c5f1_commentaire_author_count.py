"""Commentaire de source_records.author_count : rôles d'auteur

Revision ID: d4a7b2e9c5f1
Revises: c2e8f4a17b39
Create Date: 2026-11-06 15:00:00.000000

`author_count` compte les contributions sources à rôle d'auteur (`is_author_role`) : l'auteur d'un document, l'inventeur d'un brevet.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a7b2e9c5f1"
down_revision: str | Sequence[str] | None = "c2e8f4a17b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "Contributions sources de l'enregistrement source qui ont le rôle author et ne sont pas collectives, telles que la source les donne."
_AFTER = "Contributions sources de l'enregistrement source qui ont un rôle d'auteur (is_author_role) et ne sont pas collectives, telles que la source les donne."


def _comment(comment: str) -> None:
    quoted = comment.replace("'", "''")
    op.execute(f"COMMENT ON COLUMN sources.source_records.author_count IS '{quoted}'")


def upgrade() -> None:
    _comment(_AFTER)


def downgrade() -> None:
    _comment(_BEFORE)
