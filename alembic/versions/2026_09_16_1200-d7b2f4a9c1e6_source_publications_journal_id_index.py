"""Enregistrements sources : index sur la revue

Chaque fusion de revues, dans l'administration comme dans le pipeline, repointe les enregistrements de la revue absorbée (`WHERE journal_id = …`). Sans index, chaque fusion relit toute la table `source_publications`. L'index est partiel : seuls les enregistrements rattachés à une revue y figurent.

Revision ID: d7b2f4a9c1e6
Revises: a3c8e1f5d902
Create Date: 2026-09-16 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7b2f4a9c1e6"
down_revision: str | Sequence[str] | None = "a3c8e1f5d902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
CREATE INDEX idx_source_pubs_journal ON public.source_publications USING btree (journal_id) WHERE (journal_id IS NOT NULL);
"""

_DOWNGRADE = r"""
DROP INDEX public.idx_source_pubs_journal;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
