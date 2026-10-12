"""Signatures : statistique de l'absence de personne et du périmètre, sur un échantillon plus grand

Le planificateur ne rapporte pas la condition `person_id IS NULL` d'une requête à une statistique sur l'expression `(person_id IS NULL)`. La statistique concerne donc les colonnes `person_id` et `in_perimeter`.

Avec l'échantillon par défaut (30 000 lignes), la combinaison « sans personne, dans le périmètre » (0,03 % des signatures) manque à la liste des combinaisons fréquentes, et l'estimation retombe sur l'hypothèse d'indépendance. La cible 1000 décuple l'échantillon : la combinaison y entre, et l'estimation suit le nombre réel.

Revision ID: b2e4f6a8d153
Revises: a7d3e5f8c012
Create Date: 2026-10-12 23:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2e4f6a8d153"
down_revision: str | Sequence[str] | None = "a7d3e5f8c012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP STATISTICS sources.source_authorships_orphan_perimeter")
    op.execute(
        "CREATE STATISTICS sources.source_authorships_orphan_perimeter (mcv) "
        "ON person_id, in_perimeter FROM sources.source_authorships"
    )
    op.execute("ALTER STATISTICS sources.source_authorships_orphan_perimeter SET STATISTICS 1000")
    op.execute("ANALYZE sources.source_authorships")


def downgrade() -> None:
    op.execute("DROP STATISTICS sources.source_authorships_orphan_perimeter")
    op.execute(
        "CREATE STATISTICS sources.source_authorships_orphan_perimeter (mcv) "
        "ON (person_id IS NULL), in_perimeter FROM sources.source_authorships"
    )
    op.execute("ANALYZE sources.source_authorships")
