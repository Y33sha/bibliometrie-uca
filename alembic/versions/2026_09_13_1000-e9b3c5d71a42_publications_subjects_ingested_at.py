"""publications.subjects_ingested_at : date de la dernière ingestion des sujets

La phase `subjects` ingère une publication quand cette date est vide. L'enregistrement d'une publication recalculée depuis ses sources la vide ; l'ingestion la pose, que la publication ait des sujets ou non.

Reprise : une publication dont le dernier lien sujet est postérieur à sa dernière modification reçoit la date de ce lien. Les autres restent à ingérer.

Revision ID: e9b3c5d71a42
Revises: d8a2f4c61e97
Create Date: 2026-09-13 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e9b3c5d71a42"
down_revision: str | Sequence[str] | None = "d8a2f4c61e97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
ALTER TABLE public.publications ADD COLUMN subjects_ingested_at timestamp with time zone;

UPDATE public.publications p
SET subjects_ingested_at = li.last_ingest
FROM (
    SELECT publication_id, max(created_at) AS last_ingest
    FROM public.publication_subjects
    GROUP BY publication_id
) li
WHERE li.publication_id = p.id AND p.updated_at <= li.last_ingest;
"""

_DOWNGRADE = """
ALTER TABLE public.publications DROP COLUMN subjects_ingested_at;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
