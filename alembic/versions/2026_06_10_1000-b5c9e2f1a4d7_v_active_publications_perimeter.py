"""v_active_publications : restreindre au périmètre (in_perimeter)

Phase 2 du chantier création⇒fusion. La vue `v_active_publications` ne
définissait l'« actif » que par le doc_type (hors `peer_review`/`memoir`). Une
publication hors-périmètre (aucun `source_authorship` in_perimeter) est de même
nature : elle existe mais ne doit pas affleurer (listings, facets, stats,
authorships canoniques). On ajoute la condition de périmètre à la vue, qui
devient la définition unique d'« affleurant » : doc_type actif **ET** au moins
un `source_authorship` in_perimeter.

À appliquer après le réimport des thèses (qui leur pose l'adresse de
l'établissement de soutenance UCA, donc `in_perimeter`) — sinon les thèses non
encore réimportées seraient exclues à tort.

Revision ID: b5c9e2f1a4d7
Revises: a9d3f1c7e5b2
Create Date: 2026-06-10 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5c9e2f1a4d7"
down_revision: str | Sequence[str] | None = "a9d3f1c7e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW public.v_active_publications AS
            SELECT p.id
            FROM public.publications p
            WHERE p.doc_type <> ALL (
                      ARRAY['peer_review'::public.doc_type, 'memoir'::public.doc_type])
              AND EXISTS (
                  SELECT 1
                  FROM public.source_publications sp
                  JOIN public.source_authorships sa
                      ON sa.source_publication_id = sp.id
                  WHERE sp.publication_id = p.id
                    AND sa.in_perimeter = TRUE
              );
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW public.v_active_publications AS
            SELECT id
            FROM public.publications
            WHERE doc_type <> ALL (
                      ARRAY['peer_review'::public.doc_type, 'memoir'::public.doc_type]);
    """)
