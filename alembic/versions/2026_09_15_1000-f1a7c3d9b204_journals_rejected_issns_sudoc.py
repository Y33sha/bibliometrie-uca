"""Revues : ISSN invalides conservés et date de vérification dans le Sudoc

Ajoute `journals.rejected_issns`, les ISSN invalides reçus des sources pour la revue, et `journals.sudoc_checked_at`, la date de la dernière vérification de ses ISSN dans le Sudoc.

Revision ID: f1a7c3d9b204
Revises: b4d9e2a7c318
Create Date: 2026-09-15 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a7c3d9b204"
down_revision: str | Sequence[str] | None = "b4d9e2a7c318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
ALTER TABLE public.journals ADD COLUMN rejected_issns text[] NOT NULL DEFAULT '{}';
ALTER TABLE public.journals ADD COLUMN sudoc_checked_at timestamptz;

COMMENT ON COLUMN public.journals.rejected_issns IS 'ISSN invalides reçus des sources pour cette revue, tels que reçus. La vérification dans le Sudoc tente leur correction.';
COMMENT ON COLUMN public.journals.sudoc_checked_at IS 'Date de la dernière vérification des ISSN de la revue dans le Sudoc. NULL : revue jamais vérifiée.';
"""

_DOWNGRADE = r"""
ALTER TABLE public.journals DROP COLUMN sudoc_checked_at;
ALTER TABLE public.journals DROP COLUMN rejected_issns;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
