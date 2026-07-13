"""Contrainte CHECK sur journals.oa_model

Aligne le schéma sur le domaine : `oa_model` accepte le vocabulaire `OaModel` (`subscription`, `full_oa`, `repository`) ou NULL. La contrainte porte en base la règle qu'appliquent le modal d'édition admin et la coercion du repository.

Revision ID: e5c9a1f3b207
Revises: b1d7f3a9c204
Create Date: 2026-07-13 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5c9a1f3b207"
down_revision: str | Sequence[str] | None = "b1d7f3a9c204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
ALTER TABLE public.journals ADD CONSTRAINT journals_oa_model_check
    CHECK (oa_model IS NULL OR oa_model IN ('subscription', 'full_oa', 'repository'));
"""

_DOWNGRADE = """
ALTER TABLE public.journals DROP CONSTRAINT journals_oa_model_check;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
