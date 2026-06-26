"""idx_sa_pub_person : index partiel (source_publication_id, person_id)

Sert le repérage des personnes rattachées à ≥2 signatures d'une même
`source_publication` (détecteur « intrus détachables » du hub admin) : le
`GROUP BY (source_publication_id, person_id) HAVING count(*) >= 2` passe d'un
scan séquentiel + tri externe sur les ~16 M lignes (~4 s) à un index-only scan
ordonné sur les seules lignes attribuées (~650 k), agrégées sans tri.

Index partiel `WHERE person_id IS NOT NULL` : seules les signatures rattachées à
une personne entrent dans le groupement, et la colonne `person_id` y figure pour
un parcours index-only. Lecture seule, réversible.

Revision ID: e7f2a4c6b8d1
Revises: d5c8b2f1a9e3
Create Date: 2026-06-26 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7f2a4c6b8d1"
down_revision: str | Sequence[str] | None = "d5c8b2f1a9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX idx_sa_pub_person
            ON public.source_authorships (source_publication_id, person_id)
            WHERE person_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_sa_pub_person")
