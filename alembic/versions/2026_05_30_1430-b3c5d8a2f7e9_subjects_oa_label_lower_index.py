"""Index fonctionnel LOWER(label) sur les sujets OpenAlex

Supporte les JOINs case-insensitive sur la hiérarchie `parent` portée par
`subjects.ontologies.openalex_topic.parent`. OpenAlex stocke les labels
avec une casse incohérente entre un sujet et la référence `parent` qui le
désigne (ex. `Social sciences` vs `Social Sciences`, `Molecular biology`
vs `Molecular Biology`, `SURGERY` vs `Surgery`). Sans index sur la forme
normalisée, la CTE récursive qui remonte la chaîne `parent` jusqu'au
domain de tête fait des table scans à chaque niveau et explose le temps
d'exécution.

Index partiel restreint aux sujets OpenAlex : seule cette ontologie subit
le problème de casse incohérent dans nos données.

Revision ID: b3c5d8a2f7e9
Revises: e8b6c4f9d2a1
Create Date: 2026-05-30 14:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3c5d8a2f7e9"
down_revision: str | Sequence[str] | None = "e8b6c4f9d2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX idx_subjects_oa_label_lower
            ON public.subjects (LOWER(label))
            WHERE ontologies ? 'openalex_topic'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_subjects_oa_label_lower")
