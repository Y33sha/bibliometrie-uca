"""rename source_publications.external_ids->>'hal' to 'hal_id'

Phase 0 du chantier `DATA_separer-matching-normalisation.md` :
harmonisation des clés `external_ids` (cohérence avec `nnt`/`pmid`/`pmc`
qui sont des acronymes courts ; `hal` était une abréviation ambiguë
du HAL ID). Le code écrivant/lisant a été aligné dans le même commit.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-14 10:26:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE source_publications
        SET external_ids = (external_ids - 'hal') || jsonb_build_object('hal_id', external_ids->'hal')
        WHERE external_ids ? 'hal'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE source_publications
        SET external_ids = (external_ids - 'hal_id') || jsonb_build_object('hal', external_ids->'hal_id')
        WHERE external_ids ? 'hal_id'
        """
    )
