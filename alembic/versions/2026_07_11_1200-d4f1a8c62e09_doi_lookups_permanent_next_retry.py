"""doi_lookups : next_retry nullable (miss définitif) — unifie les misses DOI cross-import

Les misses de cross-import par DOI vivaient à deux endroits : `doi_lookups` (backoff daté)
pour les sources non natives, et un stub `staging` (`not_found_at`) pour les sources dont le
DOI est l'identifiant natif (crossref, datacite). On unifie sur `doi_lookups` : `next_retry`
devient nullable, `NULL` = miss définitif jamais retenté. Les stubs `staging` crossref/datacite
existants sont migrés vers `doi_lookups` (next_retry NULL) puis supprimés. Les stubs HAL (par
hal-id) ne sont pas concernés.

Revision ID: d4f1a8c62e09
Revises: a9e4c2b13f80
Create Date: 2026-07-11 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4f1a8c62e09"
down_revision: str | Sequence[str] | None = "a9e4c2b13f80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
ALTER TABLE public.doi_lookups ALTER COLUMN next_retry DROP NOT NULL;

INSERT INTO public.doi_lookups (source, doi, not_found_at, next_retry)
SELECT source, doi, COALESCE(not_found_at, now()), NULL
FROM public.staging
WHERE source::text IN ('crossref', 'datacite')
  AND not_found_at IS NOT NULL
  AND doi IS NOT NULL
ON CONFLICT (source, doi) DO UPDATE SET next_retry = NULL;

DELETE FROM public.staging
WHERE source::text IN ('crossref', 'datacite')
  AND not_found_at IS NOT NULL;
"""

_DOWNGRADE = """
UPDATE public.doi_lookups
   SET next_retry = now() + make_interval(days => 3650)
 WHERE next_retry IS NULL;

ALTER TABLE public.doi_lookups ALTER COLUMN next_retry SET NOT NULL;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
