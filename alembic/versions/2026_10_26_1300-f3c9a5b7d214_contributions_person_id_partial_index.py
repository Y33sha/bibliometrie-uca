"""Index partiel et couvrant des contributions par personne

Revision ID: f3c9a5b7d214
Revises: d8b2f6a1c093
Create Date: 2026-10-26 13:00:00.000000

Les recherches par personne lisent seulement les contributions rattachées à une personne. L'index en exclut donc les contributions sans personne, qui sont les plus nombreuses. `publication_id` et `roles` inclus permettent à la facette des auteurs de lire seulement l'index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3c9a5b7d214"
down_revision: str | Sequence[str] | None = "d8b2f6a1c093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX publications.contributions_person_id_idx")
    op.execute("""
        CREATE INDEX contributions_person_id_idx
            ON publications.contributions (person_id)
            INCLUDE (publication_id, roles)
            WHERE person_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX publications.contributions_person_id_idx")
    op.execute("CREATE INDEX contributions_person_id_idx ON publications.contributions (person_id)")
