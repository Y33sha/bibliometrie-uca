"""Positions d'auteur des contributions : correspondant, premier, dernier

La colonne `contributions.author_positions` reçoit la position de correspondant de `contributions.is_corresponding`, supprimée. Toutes les contributions sont marquées pour la recomposition de leurs attributs : la tâche `author_grouping.attributes` calcule les premiers et derniers auteurs.

Revision ID: 410d28f98e35
Revises: 5c0e7a92d4b1
Create Date: 2026-11-03 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "410d28f98e35"
down_revision: str | Sequence[str] | None = "5c0e7a92d4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
CREATE TYPE public.author_position AS ENUM (
    'corresponding',
    'first',
    'last'
);

ALTER TABLE publications.contributions
    ADD COLUMN author_positions public.author_position[] DEFAULT '{}'::public.author_position[] NOT NULL;

UPDATE publications.contributions
SET author_positions = '{corresponding}'::public.author_position[]
WHERE is_corresponding;

ALTER TABLE publications.contributions DROP COLUMN is_corresponding;

COMMENT ON COLUMN publications.contributions.author_positions IS 'Positions d''auteur : correspondant, premier ou dernier auteur. La phase author_grouping les calcule depuis les listes d''auteurs de la publication.';

INSERT INTO queues.contribution_attributes_queue (id)
SELECT id FROM publications.contributions
ON CONFLICT (id) DO UPDATE SET seq = DEFAULT;
"""

_DOWNGRADE = """
ALTER TABLE publications.contributions ADD COLUMN is_corresponding boolean;

UPDATE publications.contributions
SET is_corresponding = 'corresponding' = ANY(author_positions);

ALTER TABLE publications.contributions DROP COLUMN author_positions;
DROP TYPE public.author_position;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
