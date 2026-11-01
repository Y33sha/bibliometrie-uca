"""Pays des contributions sources à ROR sans adresse remis en file

Revision ID: 90aaceaeda15
Revises: 6c47405869dc
Create Date: 2026-11-01 05:00:00.000000

Les pays d'une contribution source viennent de ses adresses, à défaut de ses ROR sans adresse. Les contributions sources qui citent un ROR sans adresse et ont une adresse à pays sont mises en file pour le recalcul de leurs pays.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "90aaceaeda15"
down_revision: str | Sequence[str] | None = "6c47405869dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENQUEUE = """
    INSERT INTO queues.source_contribution_countries_queue (id)
    SELECT DISTINCT scr.source_contribution_id
    FROM sources.source_contribution_rors scr
    WHERE scr.address_id IS NULL
      AND EXISTS (
          SELECT 1 FROM sources.source_contribution_addresses sca
          JOIN structures.addresses a ON a.id = sca.address_id
          WHERE sca.source_contribution_id = scr.source_contribution_id
            AND cardinality(a.countries) > 0
      )
    ON CONFLICT (id) DO UPDATE SET seq = DEFAULT
"""


def upgrade() -> None:
    op.execute(_ENQUEUE)


def downgrade() -> None:
    op.execute(_ENQUEUE)
