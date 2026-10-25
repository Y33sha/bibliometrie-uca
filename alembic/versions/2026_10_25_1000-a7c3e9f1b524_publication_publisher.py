"""Éditeur des enregistrements sources et des publications, préfixe DOI des publications

Revision ID: a7c3e9f1b524
Revises: 5b8e2c7f1d39
Create Date: 2026-10-25 10:00:00.000000

`source_records.publisher_id` désigne l'éditeur que nomme la source. `publications.publisher_id` désigne l'éditeur de la publication à la date de sa publication. `publications.doi_prefix` est le préfixe du DOI, colonne générée pour les jointures sur `doi_prefixes`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c3e9f1b524"
down_revision: str | Sequence[str] | None = "5b8e2c7f1d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_records
            ADD COLUMN publisher_id integer REFERENCES publishing.publishers(id);
        CREATE INDEX idx_source_records_publisher ON sources.source_records (publisher_id)
            WHERE publisher_id IS NOT NULL;
        COMMENT ON COLUMN sources.source_records.publisher_id IS
            'Éditeur que nomme la source. Nul pour une production hébergée sans être publiée.';

        ALTER TABLE publications.publications
            ADD COLUMN publisher_id integer REFERENCES publishing.publishers(id),
            ADD COLUMN doi_prefix text GENERATED ALWAYS AS (split_part(doi, '/', 1)) STORED;
        CREATE INDEX idx_publications_publisher ON publications.publications (publisher_id)
            WHERE publisher_id IS NOT NULL;
        CREATE INDEX idx_publications_doi_prefix ON publications.publications (doi_prefix)
            WHERE doi_prefix IS NOT NULL;
        COMMENT ON COLUMN publications.publications.publisher_id IS
            'Éditeur à la date de publication : titulaire du préfixe du DOI Crossref, à défaut éditeur des enregistrements sources.';
        COMMENT ON COLUMN publications.publications.doi_prefix IS
            'Préfixe du DOI, pour les jointures sur doi_prefixes.';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE publications.publications DROP COLUMN doi_prefix, DROP COLUMN publisher_id;
        ALTER TABLE sources.source_records DROP COLUMN publisher_id;
    """)
