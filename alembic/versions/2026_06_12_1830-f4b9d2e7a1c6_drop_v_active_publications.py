"""Suppression de la vue v_active_publications (scope doc_type inline via domain/publications/scope)

La vue ne faisait qu'exclure les doc_types hors-scope (peer_review, memoir) pour
les jointures pipeline (build_authorships, persons_create). Le planificateur
inline une vue : aucun gain reel sur un simple filtre `doc_type NOT IN (...)`. La
source unique de verite est la constante OUT_OF_SCOPE_DOC_TYPES_SQL
(domain/publications/scope), desormais inlinee dans ces deux requetes comme cote
API. On supprime la vue (et son test garde-fou anti-divergence).

La migration b5c9e2f1a4d7 lui avait ajoute une condition de perimetre, a tort :
elle excluait les publications hors-perimetre des vues qui doivent tout montrer
(page personne). Le perimetre est un filtre PAR REQUETE (listes UCA), porte par
la colonne materialisee publications.in_perimeter (e7f2a9c4b1d3).

Revision ID: f4b9d2e7a1c6
Revises: e7f2a9c4b1d3
Create Date: 2026-06-12 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b9d2e7a1c6"
down_revision: str | Sequence[str] | None = "e7f2a9c4b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public.v_active_publications")


def downgrade() -> None:
    # Restaure l'etat immediatement anterieur (vue + condition de perimetre,
    # telle que posee par b5c9e2f1a4d7).
    op.execute("""
        CREATE VIEW public.v_active_publications AS
            SELECT p.id
            FROM public.publications p
            WHERE p.doc_type <> ALL (
                      ARRAY['peer_review'::public.doc_type, 'memoir'::public.doc_type])
              AND EXISTS (
                  SELECT 1
                  FROM public.source_publications sp
                  JOIN public.source_authorships sa ON sa.source_publication_id = sp.id
                  WHERE sp.publication_id = p.id AND sa.in_perimeter = TRUE
              );
    """)
