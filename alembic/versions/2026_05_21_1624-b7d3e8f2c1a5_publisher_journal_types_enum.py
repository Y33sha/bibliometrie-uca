"""publisher_type + journal_type : enums SQL + colonnes typées

Phase 1 du chantier `METIER_publishers-journals.md`. Deux enums introduits
pour qualifier publishers et journals :

- `publisher_type` (nouveau) : `commercial`, `learned_society`, `academic_institution`, `repository`, `aggregator`, `unknown`. Colonne ajoutée à `publishers` avec default `'unknown'`.
- `journal_type` (existant en `text` avec default `'journal'`) : converti en enum (`journal`, `proceedings`, `repository`, `book_series`, `preprint_server`, `media`). Les 4 valeurs déjà présentes en base (`journal`, `repository`, `media`, `book_series`) sont toutes dans la liste cible, donc pas de mapping à appliquer avant le ALTER COLUMN.

Revision ID: b7d3e8f2c1a5
Revises: a3f7b2c9d4e1
Create Date: 2026-05-21 16:24:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d3e8f2c1a5"
down_revision: str | Sequence[str] | None = "a3f7b2c9d4e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE publisher_type AS ENUM (
            'commercial',
            'learned_society',
            'academic_institution',
            'repository',
            'aggregator',
            'unknown'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE journal_type AS ENUM (
            'journal',
            'proceedings',
            'repository',
            'book_series',
            'preprint_server',
            'media'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE publishers
        ADD COLUMN publisher_type publisher_type NOT NULL DEFAULT 'unknown'
        """
    )
    # `ALTER COLUMN ... TYPE` recrée le default à zéro côté PostgreSQL si on
    # ne le réaffirme pas explicitement — on dépose puis on repose pour
    # éviter un état transitoire ambigu.
    op.execute("ALTER TABLE journals ALTER COLUMN journal_type DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE journals
        ALTER COLUMN journal_type TYPE journal_type
        USING journal_type::journal_type
        """
    )
    op.execute("ALTER TABLE journals ALTER COLUMN journal_type SET DEFAULT 'journal'::journal_type")


def downgrade() -> None:
    op.execute("ALTER TABLE journals ALTER COLUMN journal_type DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE journals
        ALTER COLUMN journal_type TYPE text
        USING journal_type::text
        """
    )
    op.execute("ALTER TABLE journals ALTER COLUMN journal_type SET DEFAULT 'journal'::text")
    op.execute("ALTER TABLE publishers DROP COLUMN publisher_type")
    op.execute("DROP TYPE journal_type")
    op.execute("DROP TYPE publisher_type")
