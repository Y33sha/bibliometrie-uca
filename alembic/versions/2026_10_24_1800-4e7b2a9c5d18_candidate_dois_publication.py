"""Publication des DOI candidats : candidate_dois.publication_id

Revision ID: 4e7b2a9c5d18
Revises: 9b5e3c1d7a42
Create Date: 2026-10-24 18:00:00.000000

La recherche des documents absents d'une source borne ses DOI candidats à la fenêtre d'années du run, par les enregistrements sources de leur publication.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4e7b2a9c5d18"
down_revision: str | Sequence[str] | None = "9b5e3c1d7a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW sources.candidate_dois AS
        SELECT DISTINCT k.doi, k.source, k.publication_id
        FROM sources.known_dois k
        JOIN publications.publications p ON p.id = k.publication_id
        WHERE p.in_perimeter
    """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW sources.candidate_dois;
        CREATE VIEW sources.candidate_dois AS
        SELECT DISTINCT k.doi, k.source
        FROM sources.known_dois k
        JOIN publications.publications p ON p.id = k.publication_id
        WHERE p.in_perimeter
    """)
