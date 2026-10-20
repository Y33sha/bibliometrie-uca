"""Colonnes de publication_author_alignment : source_records et source_contributions

Revision ID: c4d8e2f7a913
Revises: b7e1c4a9d2f6
Create Date: 2026-10-21 09:00:00.000000

`publications.publication_author_alignment` nomme ses décomptes `source_records` (enregistrements sources de la publication) et `source_contributions` (contributions sources d'auteur).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4d8e2f7a913"
down_revision: str | Sequence[str] | None = "b7e1c4a9d2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMES = (("notices", "source_records"), ("signatures", "source_contributions"))


def upgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            "ALTER MATERIALIZED VIEW publications.publication_author_alignment "
            f"RENAME COLUMN {old} TO {new}"
        )


def downgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            "ALTER MATERIALIZED VIEW publications.publication_author_alignment "
            f"RENAME COLUMN {new} TO {old}"
        )
