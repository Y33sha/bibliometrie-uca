"""Suppression des APC de catalogue des publications en série

Revision ID: b7e4d2a9c815
Revises: 80a709701aee
Create Date: 2026-10-26 15:00:00.000000

Supprime `serials.apc_amount` et `serials.apc_currency`, et retire le marqueur de saisie manuelle `apc` de `manual_fields`. Les frais de publication payés sont dans `apc_payments`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e4d2a9c815"
down_revision: str | Sequence[str] | None = "80a709701aee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE publishing.serials SET manual_fields = array_remove(manual_fields, 'apc') "
        "WHERE 'apc' = ANY(manual_fields)"
    )
    op.execute("ALTER TABLE publishing.serials DROP COLUMN apc_amount, DROP COLUMN apc_currency")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE publishing.serials "
        "ADD COLUMN apc_amount numeric(10,2), ADD COLUMN apc_currency text DEFAULT 'EUR'"
    )
