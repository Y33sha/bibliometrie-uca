"""publications : contrainte UNIQUE(lower(doi)) → index simple

Phase 2 du chantier création⇒fusion. Pour créer une publication par
`source_publication` puis dédoublonner par fusion (Phase 3), deux
source_publications à même DOI doivent pouvoir coexister transitoirement.
L'unicité « 1 DOI = 1 publication » passe donc de garantie DB à garantie
pipeline (la passe de fusion la rétablit). On remplace l'index UNIQUE par un
index simple, toujours utile au lookup `find_by_doi` et aux rattachements.

Revision ID: c6d0f3a2b5e8
Revises: b5c9e2f1a4d7
Create Date: 2026-06-10 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c6d0f3a2b5e8"
down_revision: str | Sequence[str] | None = "b5c9e2f1a4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.publications_doi_lower_key")
    op.execute(
        "CREATE INDEX idx_publications_doi_lower "
        "ON public.publications (lower(doi)) WHERE doi IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_publications_doi_lower")
    op.execute(
        "CREATE UNIQUE INDEX publications_doi_lower_key "
        "ON public.publications (lower(doi)) WHERE doi IS NOT NULL"
    )
