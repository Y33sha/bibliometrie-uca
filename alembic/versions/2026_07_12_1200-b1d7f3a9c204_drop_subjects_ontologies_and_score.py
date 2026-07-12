"""Supprime subjects.ontologies et publication_subjects.score

La phase sujets n'écrit plus d'ontologies (`codes`/`level`/`parent`) ni de score : un sujet se réduit à son libellé, la provenance vit sur `publication_subjects.source`. On retire les colonnes devenues inutilisées, et l'index partiel qui n'existait que pour les concepts OpenAlex.

Revision ID: b1d7f3a9c204
Revises: d4f1a8c62e09
Create Date: 2026-07-12 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b1d7f3a9c204"
down_revision: str | Sequence[str] | None = "d4f1a8c62e09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
DROP INDEX IF EXISTS public.idx_subjects_oa_label_lower;
ALTER TABLE public.subjects DROP COLUMN ontologies;
ALTER TABLE public.publication_subjects DROP COLUMN score;
"""

_DOWNGRADE = """
ALTER TABLE public.publication_subjects ADD COLUMN score real;
ALTER TABLE public.subjects ADD COLUMN ontologies jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX idx_subjects_oa_label_lower ON public.subjects USING btree (lower(label))
    WHERE (ontologies ? 'openalex_topic'::text);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
