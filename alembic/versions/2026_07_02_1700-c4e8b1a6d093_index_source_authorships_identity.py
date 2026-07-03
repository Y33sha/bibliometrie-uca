"""index sur source_authorships.identity_id

Index de la FK d'identité, requis par trois usages : le balayage des identités orphelines en fin de `normalize` (`DELETE FROM author_identifying_keys WHERE NOT EXISTS (… identity_id …)`, sinon un seq scan de `source_authorships` par identité), les jointures des lecteurs vers `author_identifying_keys`, et la contrainte FK posée à la phase de contraction.

Revision ID: c4e8b1a6d093
Revises: a5d9c3e17f42
Create Date: 2026-07-02 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8b1a6d093"
down_revision: str | Sequence[str] | None = "a5d9c3e17f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX idx_sa_identity ON public.source_authorships (identity_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_sa_identity")
