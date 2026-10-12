"""Préfixes DOI : une date d'interrogation par agence

`crossref_checked_at` et `datacite_checked_at` retiennent que l'agence a répondu, préfixe connu ou non. Un préfixe d'agence inconnue passe chez DataCite après que Crossref l'a interrogé sans le trouver.

Reprise : la date de `publisher_checked_at` va dans la colonne de l'agence du préfixe. Les préfixes d'agence inconnue restent sans date et sont interrogés de nouveau.

Revision ID: e3b7c9d1f052
Revises: d8a4b1c6e270
Create Date: 2026-10-12 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3b7c9d1f052"
down_revision: str | Sequence[str] | None = "d8a4b1c6e270"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE publishing.doi_prefixes
            ADD COLUMN crossref_checked_at timestamptz,
            ADD COLUMN datacite_checked_at timestamptz
    """)
    op.execute("""
        UPDATE publishing.doi_prefixes
        SET crossref_checked_at = CASE WHEN ra = 'Crossref' THEN publisher_checked_at END,
            datacite_checked_at = CASE WHEN ra = 'DataCite' THEN publisher_checked_at END
        WHERE publisher_checked_at IS NOT NULL
    """)
    op.execute("ALTER TABLE publishing.doi_prefixes DROP COLUMN publisher_checked_at")


def downgrade() -> None:
    op.execute("ALTER TABLE publishing.doi_prefixes ADD COLUMN publisher_checked_at timestamptz")
    op.execute("""
        UPDATE publishing.doi_prefixes
        SET publisher_checked_at = COALESCE(crossref_checked_at, datacite_checked_at)
    """)
    op.execute("""
        CREATE INDEX idx_doi_prefixes_publisher_pending ON publishing.doi_prefixes (prefix)
        WHERE publisher_id IS NULL AND publisher_checked_at IS NULL
    """)
    op.execute("""
        ALTER TABLE publishing.doi_prefixes
            DROP COLUMN crossref_checked_at,
            DROP COLUMN datacite_checked_at
    """)
