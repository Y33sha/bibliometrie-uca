"""Recherches infructueuses : doi.org retiré des sources

Revision ID: 7c3f1a9e5b24
Revises: b2e6d9a4c7f1
Create Date: 2026-11-27 14:00:00.000000

La réponse de doi.org sur un DOI est dans `dois.registered`. `failed_lookups.source` prend les seules sources de `source_type`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c3f1a9e5b24"
down_revision: str | Sequence[str] | None = "b2e6d9a4c7f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENT = (
    "Identifiants cherchés en vain par la phase fetch_missing dans une source. L''échec est "
    "définitif pour un identifiant absent de son registre (hal-id dans HAL, NNT dans "
    "theses.fr). Les autres recherches reprennent quand not_found_at date de plus que le délai "
    "fetch_missing_retry_after_days."
)

_PREVIOUS_COMMENT = (
    "Identifiants cherchés en vain par la phase fetch_missing, dans une source ou auprès de "
    "doi.org (source doi_org : DOI que doi.org ne connaît pas). L''échec est définitif pour un "
    "identifiant absent de son registre (hal-id dans HAL, NNT dans theses.fr, DOI auprès de "
    "doi.org). Les autres recherches reprennent quand not_found_at date de plus que le délai "
    "fetch_missing_retry_after_days."
)


def upgrade() -> None:
    op.execute(f"""
        DELETE FROM sources.failed_lookups WHERE source = 'doi_org';
        ALTER TYPE public.lookup_source RENAME TO lookup_source_previous;
        CREATE TYPE public.lookup_source AS ENUM (
            'hal', 'openalex', 'wos', 'scanr', 'ops', 'theses', 'crossref', 'datacite', 'inspire'
        );
        ALTER TABLE sources.failed_lookups
            ALTER COLUMN source TYPE public.lookup_source USING source::text::public.lookup_source;
        DROP TYPE public.lookup_source_previous;
        COMMENT ON TABLE sources.failed_lookups IS '{_COMMENT}';
    """)


def downgrade() -> None:
    op.execute(f"""
        ALTER TYPE public.lookup_source ADD VALUE IF NOT EXISTS 'doi_org';
        COMMENT ON TABLE sources.failed_lookups IS '{_PREVIOUS_COMMENT}';
    """)
