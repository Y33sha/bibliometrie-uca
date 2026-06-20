"""source_type : ajouter la valeur d'enum 'datacite'

DataCite devient une source ingérée par DOI (cross-import, comme Crossref).
Le registre Python correspondant est `domain.sources.registry` (ALL_SOURCES,
DOI_SEARCHABLE_SOURCES, SOURCE_PRIORITY).

Revision ID: b7d3f2a9c1e4
Revises: a2f8c4d6e1b9
Create Date: 2026-06-20 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d3f2a9c1e4"
down_revision: str | Sequence[str] | None = "a2f8c4d6e1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.source_type ADD VALUE IF NOT EXISTS 'datacite'")


def downgrade() -> None:
    # Postgres ne permet pas `ALTER TYPE ... DROP VALUE` directement ; pour
    # rollback il faudrait recréer l'enum sans la valeur et basculer toutes les
    # colonnes via cast. Cas peu probable — non implémenté.
    raise NotImplementedError("Postgres ne supporte pas le DROP VALUE sur enum")
