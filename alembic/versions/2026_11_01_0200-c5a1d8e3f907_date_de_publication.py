"""Date de publication et sa précision

Revision ID: c5a1d8e3f907
Revises: b3e9f7a2c618
Create Date: 2026-11-01 02:00:00.000000

Les enregistrements sources et les publications reçoivent une date de publication et sa précision (année, mois, jour). Une date à l'année tombe le 1er janvier, une date au mois le 1er du mois. Chaque ligne à année reçoit la date à l'année de son `publication_year`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5a1d8e3f907"
down_revision: str | Sequence[str] | None = "b3e9f7a2c618"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.date_precision AS ENUM ('year', 'month', 'day');
    """)
    for table in ("sources.source_records", "publications.publications"):
        op.execute(f"""
            ALTER TABLE {table}
                ADD COLUMN publication_date date,
                ADD COLUMN publication_date_precision public.date_precision;
            UPDATE {table}
            SET publication_date = make_date(publication_year, 1, 1),
                publication_date_precision = 'year'
            WHERE publication_year IS NOT NULL;
            COMMENT ON COLUMN {table}.publication_date IS
            'Date de publication. À l''année : 1er janvier ; au mois : 1er du mois.';
            COMMENT ON COLUMN {table}.publication_date_precision IS
            'Précision de publication_date : year, month ou day.';
        """)


def downgrade() -> None:
    for table in ("sources.source_records", "publications.publications"):
        op.execute(f"""
            ALTER TABLE {table}
                DROP COLUMN publication_date,
                DROP COLUMN publication_date_precision;
        """)
    op.execute("DROP TYPE public.date_precision")
