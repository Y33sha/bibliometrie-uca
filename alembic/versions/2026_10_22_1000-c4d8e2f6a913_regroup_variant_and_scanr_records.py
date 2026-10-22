"""Publications à regrouper : copies d'un article dans un repository et enregistrements sources scanR issus d'un dépôt HAL

Revision ID: c4d8e2f6a913
Revises: a9e4c7b2d618
Create Date: 2026-10-22 10:00:00.000000

L'alignement des auteurs écarte seulement les versions d'un concept et les pièces d'un jeu de données. Les publications qui ont une copie d'un article dans un repository (`DATACITE_VARIANT_TO_PRIMARY`), ou un enregistrement source scanR issu d'un dépôt HAL présent, sont marquées à regrouper.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4d8e2f6a913"
down_revision: str | Sequence[str] | None = "a9e4c7b2d618"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE publications.publications p SET contributions_dirty = true
        WHERE NOT p.contributions_dirty AND EXISTS (
            SELECT 1 FROM sources.source_records sr
            WHERE sr.publication_id = p.id
              AND (sr.corrections -> 'doi' ->> 'corrected_by' = 'DATACITE_VARIANT_TO_PRIMARY'
                   OR (sr.source = 'scanr' AND sr.source_id ILIKE 'hal%' AND EXISTS (
                       SELECT 1 FROM sources.source_records h
                       WHERE h.publication_id = p.id AND h.source = 'hal')))
        )
    """)


def downgrade() -> None:
    pass
