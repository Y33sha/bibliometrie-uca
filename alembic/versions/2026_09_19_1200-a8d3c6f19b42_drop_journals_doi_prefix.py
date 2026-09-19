"""Revues : suppression de `journals.doi_prefix`

Supprime la colonne `journals.doi_prefix` et son index. La descente les recrée, vides.

Revision ID: a8d3c6f19b42
Revises: c5e9a2d4f817
Create Date: 2026-09-19 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8d3c6f19b42"
down_revision: str | Sequence[str] | None = "c5e9a2d4f817"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
DROP INDEX IF EXISTS public.idx_journals_doi_prefix;
ALTER TABLE public.journals DROP COLUMN doi_prefix;
"""

_DOWNGRADE = r"""
ALTER TABLE public.journals ADD COLUMN doi_prefix text;
CREATE INDEX idx_journals_doi_prefix ON public.journals USING btree (doi_prefix) WHERE (doi_prefix IS NOT NULL);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
