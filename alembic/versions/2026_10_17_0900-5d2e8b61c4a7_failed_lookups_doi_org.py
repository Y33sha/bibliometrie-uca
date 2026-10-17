"""Échecs de recherche : doi.org parmi les sources interrogées, reprise selon le délai configuré

`failed_lookups.source` prend le type `lookup_source` : les sources de notices, plus `doi_org`. Une ligne `doi_org` note un DOI que doi.org ne connaît pas. La colonne `next_retry` disparaît : une recherche reprend quand `not_found_at` date de plus que le délai `fetch_missing_retry_after_days`.

Revision ID: 5d2e8b61c4a7
Revises: c3a1f0d27b94
Create Date: 2026-10-17 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d2e8b61c4a7"
down_revision: str | Sequence[str] | None = "c3a1f0d27b94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.lookup_source AS ENUM (
            'hal', 'openalex', 'wos', 'scanr', 'theses', 'crossref', 'datacite', 'doi_org'
        );
        ALTER TABLE sources.failed_lookups
            ALTER COLUMN source TYPE public.lookup_source USING source::text::public.lookup_source;
        ALTER TABLE sources.failed_lookups DROP COLUMN next_retry;
        COMMENT ON TABLE sources.failed_lookups IS
            'Identifiants cherchés en vain par la phase fetch_missing, dans une source ou auprès de doi.org (source doi_org : DOI que doi.org ne connaît pas). La recherche reprend quand not_found_at date de plus que le délai fetch_missing_retry_after_days.';
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM sources.failed_lookups WHERE source = 'doi_org';
        ALTER TABLE sources.failed_lookups ADD COLUMN next_retry timestamptz;
        UPDATE sources.failed_lookups SET next_retry = not_found_at + interval '30 days';
        ALTER TABLE sources.failed_lookups
            ALTER COLUMN source TYPE public.source_type USING source::text::public.source_type;
        DROP TYPE public.lookup_source;
    """)
