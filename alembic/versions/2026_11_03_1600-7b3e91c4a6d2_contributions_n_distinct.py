"""Contributions : nombre de publications et d'enregistrements sources distincts fixé pour le planificateur

L'échantillon d'`ANALYZE` sous-estime le nombre de valeurs distinctes de deux colonnes. `contributions.publication_id` : 5 781 publications estimées, 78 628 réelles. `aligned_source_contributions.source_record_id` : 13 919 enregistrements sources estimés, 289 157 réels. Le planificateur attend environ 900 contributions par publication, pour 70 réelles. Le recalcul des attributs des contributions d'une publication, pendant la fusion manuelle, compile alors en JIT un plan surestimé et dure plusieurs secondes.

`n_distinct` négatif donne le nombre de valeurs distinctes en proportion des lignes, quel que soit le volume.

Revision ID: 7b3e91c4a6d2
Revises: 410d28f98e35
Create Date: 2026-11-03 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7b3e91c4a6d2"
down_revision: str | Sequence[str] | None = "410d28f98e35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = (
    ("publications.contributions", "publication_id", -0.0144),
    ("publications.aligned_source_contributions", "source_record_id", -0.0135),
)


def upgrade() -> None:
    for table, column, n_distinct in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET (n_distinct = {n_distinct})")
        op.execute(f"ANALYZE {table} ({column})")


def downgrade() -> None:
    for table, column, _ in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} RESET (n_distinct)")
        op.execute(f"ANALYZE {table} ({column})")
