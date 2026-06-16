"""publications : rétablir UNIQUE(lower(doi))

Inverse de `c6d0f3a2b5e8` (qui avait dégradé l'unique en index simple pour
laisser cohabiter transitoirement deux publications au même DOI pendant l'ère
création⇒fusion). L'unicité « 1 DOI = 1 publication » redevient une garantie DB :
la réconciliation des composantes assigne chaque source_publication à l'unique
pub-ancre de sa partition `(composante ∩ DOI)`, donc ne produit jamais deux
publications au même DOI. Prérequis (vérifié) : le stock ne porte plus de
doublon `lower(doi)`. Index partiel : les publications sans DOI ne sont pas
contraintes.

Revision ID: 94c27bec8361
Revises: b2e8d4a1f6c3
Create Date: 2026-06-16 15:35:36.156550

"""

from collections.abc import Sequence

from alembic import op

revision: str = "94c27bec8361"
down_revision: str | Sequence[str] | None = "b2e8d4a1f6c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_publications_doi_lower")
    op.execute(
        "CREATE UNIQUE INDEX publications_doi_lower_key "
        "ON public.publications (lower(doi)) WHERE doi IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.publications_doi_lower_key")
    op.execute(
        "CREATE INDEX idx_publications_doi_lower "
        "ON public.publications (lower(doi)) WHERE doi IS NOT NULL"
    )
