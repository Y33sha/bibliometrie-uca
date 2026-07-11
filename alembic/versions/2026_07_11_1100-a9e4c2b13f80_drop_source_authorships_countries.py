"""source_authorships : suppression du cache pays

`source_authorships.countries` est un cache dénormalisé dont l'unique lecteur est le tableau
de cohérence des sources de la page publication, qui peut dériver les pays par signature
directement des adresses jointes. La colonne n'alimente aucun autre calcul :
`source_publications.countries` et `publications.countries` se recalculent directement depuis
les adresses. On la supprime. Le flag `countries_dirty` (source_authorships) reste : il borne
le refresh des caches aval.

Revision ID: a9e4c2b13f80
Revises: c7d2f9a41e08
Create Date: 2026-07-11 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9e4c2b13f80"
down_revision: str | Sequence[str] | None = "c7d2f9a41e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.source_authorships DROP COLUMN countries;")


def downgrade() -> None:
    op.execute("ALTER TABLE public.source_authorships ADD COLUMN countries text[];")
