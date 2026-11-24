"""Date d'indexation Crossref retirée de source_extras

La clé `indexed` de `source_extras`, recopiée de l'horodatage de réindexation de Crossref, est retirée des enregistrements sources et des publications. Un `source_extras` vidé devient NULL.

Revision ID: d4b8f2a05c31
Revises: e5c9a3b16d42
Create Date: 2026-11-23 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4b8f2a05c31"
down_revision: str | Sequence[str] | None = "e5c9a3b16d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("sources.source_records", "publications.publications"):
        op.execute(
            f"UPDATE {table} SET source_extras = NULLIF(source_extras - 'indexed', '{{}}'::jsonb)"
            " WHERE source_extras ? 'indexed'"
        )


def downgrade() -> None:
    """Les dates d'indexation retirées reviennent à la normalisation suivante de chaque enregistrement source Crossref, avec le code qui les écrit."""
