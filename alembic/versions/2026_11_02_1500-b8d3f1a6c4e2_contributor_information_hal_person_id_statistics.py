"""Statistiques des informations du contributeur par compte HAL

Revision ID: b8d3f1a6c4e2
Revises: e4a7c2d9b6f1
Create Date: 2026-11-02 15:00:00.000000

PostgreSQL tire seulement des index non partiels les statistiques d'une expression. Sans statistiques, le planificateur estime à environ 300 les lignes d'un compte HAL, contre une ou deux en réalité, et délaisse l'index `contributor_information_hal_person_id_idx`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d3f1a6c4e2"
down_revision: str | Sequence[str] | None = "e4a7c2d9b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE STATISTICS sources.contributor_information_hal_person_id_stat"
        " ON ((identifiers ->> 'hal_person_id')) FROM sources.contributor_information"
    )
    op.execute("ANALYZE sources.contributor_information")


def downgrade() -> None:
    op.execute("DROP STATISTICS sources.contributor_information_hal_person_id_stat")
