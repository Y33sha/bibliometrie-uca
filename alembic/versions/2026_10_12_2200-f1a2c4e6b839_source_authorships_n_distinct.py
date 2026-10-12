"""Signatures : nombre de notices distinctes fixé pour le planificateur

L'échantillon d'`ANALYZE` sous-estime le nombre de notices distinctes de `source_authorships.source_publication_id` : 12 252 estimées, 292 694 réelles. Le planificateur attend alors environ 1 800 signatures par notice au lieu de 75, et choisit un plan parallèle pour la lecture des signatures d'une notice. Le lancement d'un processus auxiliaire coûte plus que la requête.

`n_distinct` négatif donne le nombre de valeurs distinctes en proportion des lignes : une notice pour 75 signatures, quel que soit le volume.

Revision ID: f1a2c4e6b839
Revises: e3b7c9d1f052
Create Date: 2026-10-12 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a2c4e6b839"
down_revision: str | Sequence[str] | None = "e3b7c9d1f052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sources.source_authorships "
        "ALTER COLUMN source_publication_id SET (n_distinct = -0.0134)"
    )
    op.execute("ANALYZE sources.source_authorships (source_publication_id)")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sources.source_authorships ALTER COLUMN source_publication_id RESET (n_distinct)"
    )
    op.execute("ANALYZE sources.source_authorships (source_publication_id)")
