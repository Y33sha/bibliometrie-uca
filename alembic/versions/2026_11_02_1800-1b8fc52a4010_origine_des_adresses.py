"""Origine du texte des adresses : adresse brute, libellé HAL ou nom seul

La colonne naît vide. La phase `affiliations` la remplit sur les adresses sans origine.

Revision ID: 1b8fc52a4010
Revises: 79fc60e8c39d
Create Date: 2026-11-02 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1b8fc52a4010"
down_revision: str | Sequence[str] | None = "79fc60e8c39d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
CREATE TYPE public.address_origin AS ENUM (
    'raw',
    'hal_label',
    'name_only'
);

ALTER TABLE structures.addresses ADD COLUMN origin public.address_origin;

COMMENT ON COLUMN structures.addresses.origin IS 'Origine du texte : adresse brute, libellé HAL ou nom seul. La phase affiliations la pose sur les adresses sans origine.';
"""

_DOWNGRADE = """
ALTER TABLE structures.addresses DROP COLUMN origin;
DROP TYPE public.address_origin;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
