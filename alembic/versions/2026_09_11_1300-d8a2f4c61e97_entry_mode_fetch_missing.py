"""staging.entry_mode : valeurs nommées d'après la phase fetch_missing

Les valeurs `cross_import_doi` et `cross_import_hal` deviennent `fetch_missing_doi` et `fetch_missing_hal`, du nom de la phase qui pose ces lignes. La description du plafond `fetch_missing_max_per_source` nomme la phase de la même façon.

Revision ID: d8a2f4c61e97
Revises: c6e1a93f5b28
Create Date: 2026-09-11 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d8a2f4c61e97"
down_revision: str | Sequence[str] | None = "c6e1a93f5b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
ALTER TABLE public.staging DROP CONSTRAINT staging_entry_mode_check;

UPDATE public.staging SET entry_mode = 'fetch_missing_doi' WHERE entry_mode = 'cross_import_doi';
UPDATE public.staging SET entry_mode = 'fetch_missing_hal' WHERE entry_mode = 'cross_import_hal';

ALTER TABLE public.staging ADD CONSTRAINT staging_entry_mode_check
    CHECK (entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text]));

UPDATE public.config
SET description = 'Nombre maximum de DOI interrogés par source cible à la phase fetch_missing, par run. 0 = illimité.'
WHERE key = 'fetch_missing_max_per_source';
"""

_DOWNGRADE = """
ALTER TABLE public.staging DROP CONSTRAINT staging_entry_mode_check;

UPDATE public.staging SET entry_mode = 'cross_import_doi' WHERE entry_mode = 'fetch_missing_doi';
UPDATE public.staging SET entry_mode = 'cross_import_hal' WHERE entry_mode = 'fetch_missing_hal';

ALTER TABLE public.staging ADD CONSTRAINT staging_entry_mode_check
    CHECK (entry_mode = ANY (ARRAY['bulk'::text, 'cross_import_doi'::text, 'cross_import_hal'::text]));

UPDATE public.config
SET description = 'Nombre maximum de DOI interrogés par source cible au cross-import, par run. 0 = illimité.'
WHERE key = 'fetch_missing_max_per_source';
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
