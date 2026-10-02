"""Signatures : index partiel sur les signatures du périmètre sans personne

La file des signatures orphelines et la cascade de la phase `persons` cherchent les signatures du périmètre qu'aucune personne ne porte. L'index partiel les désigne sans parcourir toutes les signatures du périmètre.

Revision ID: e7c4a2f9b158
Revises: b6e2d9a4c731
Create Date: 2026-10-02 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7c4a2f9b158"
down_revision: str | Sequence[str] | None = "b6e2d9a4c731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_sa_orphan_in_perimeter ON public.source_authorships USING btree (id) "
        "WHERE (person_id IS NULL AND in_perimeter)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX public.idx_sa_orphan_in_perimeter")
