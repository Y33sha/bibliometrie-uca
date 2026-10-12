"""Signatures : répartition conjointe de l'absence de personne et du périmètre

Le planificateur multiplie la part des signatures sans personne par la part des signatures du périmètre, comme si les deux conditions étaient indépendantes. Presque toutes les signatures du périmètre ont une personne : il estimait 380 000 signatures du périmètre sans personne pour 6 181 réelles, et parcourait toute la table au lieu de l'index partiel `idx_sa_orphan_in_perimeter`.

La statistique étendue donne la fréquence de chaque combinaison des deux conditions.

Revision ID: a7d3e5f8c012
Revises: f1a2c4e6b839
Create Date: 2026-10-12 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e5f8c012"
down_revision: str | Sequence[str] | None = "f1a2c4e6b839"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE STATISTICS sources.source_authorships_orphan_perimeter (mcv) "
        "ON (person_id IS NULL), in_perimeter FROM sources.source_authorships"
    )
    op.execute("ANALYZE sources.source_authorships")


def downgrade() -> None:
    op.execute("DROP STATISTICS sources.source_authorships_orphan_perimeter")
