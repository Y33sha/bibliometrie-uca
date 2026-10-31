"""Année de publication générée depuis la date

Revision ID: d7f2b9c4e016
Revises: c5a1d8e3f907
Create Date: 2026-11-01 03:00:00.000000

`publication_year` devient une colonne générée depuis `publication_date`, sur les enregistrements sources et les publications. Une ligne à année sans date reçoit d'abord la date à l'année. La date et sa précision sont obligatoires sur les publications.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7f2b9c4e016"
down_revision: str | Sequence[str] | None = "c5a1d8e3f907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("sources.source_records", "publications.publications")

_PUBLICATION_INDEXES = """
    CREATE INDEX idx_publications_in_perimeter_year
        ON publications.publications USING btree (publication_year DESC) WHERE in_perimeter;
    CREATE INDEX idx_publications_year ON publications.publications USING btree (publication_year);
    CREATE INDEX idx_publications_year_type
        ON publications.publications USING btree (publication_year, doc_type);
"""


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"""
            UPDATE {table}
            SET publication_date = make_date(publication_year, 1, 1),
                publication_date_precision = 'year'
            WHERE publication_date IS NULL AND publication_year IS NOT NULL;
            ALTER TABLE {table} DROP COLUMN publication_year;
            ALTER TABLE {table} ADD COLUMN publication_year smallint
                GENERATED ALWAYS AS (EXTRACT(YEAR FROM publication_date)::smallint) STORED;
            COMMENT ON COLUMN {table}.publication_year IS 'Année de publication_date.';
        """)
    op.execute(f"""
        ALTER TABLE publications.publications
            ALTER COLUMN publication_date SET NOT NULL,
            ALTER COLUMN publication_date_precision SET NOT NULL;
        {_PUBLICATION_INDEXES}
    """)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"""
            ALTER TABLE {table} DROP COLUMN publication_year;
            ALTER TABLE {table} ADD COLUMN publication_year smallint;
            UPDATE {table} SET publication_year = EXTRACT(YEAR FROM publication_date)::smallint;
        """)
    op.execute(f"""
        ALTER TABLE publications.publications
            ALTER COLUMN publication_date DROP NOT NULL,
            ALTER COLUMN publication_date_precision DROP NOT NULL,
            ALTER COLUMN publication_year SET NOT NULL;
        {_PUBLICATION_INDEXES}
    """)
