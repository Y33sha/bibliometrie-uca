"""Formes de nom des personnes : nom et prénom normalisés

`person_name_forms` gagne `last_name_normalized` et `first_name_normalized`, renseignés au fil de la conversion des formes, chaîne unique `name_form` jusque-là.

Revision ID: b2e7c4a9f513
Revises: a7d3e9c1f264
Create Date: 2026-10-06 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2e7c4a9f513"
down_revision: str | Sequence[str] | None = "a7d3e9c1f264"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE public.person_name_forms
            ADD COLUMN last_name_normalized text,
            ADD COLUMN first_name_normalized text,
            ADD CONSTRAINT person_name_forms_split CHECK (
                first_name_normalized IS NULL OR last_name_normalized IS NOT NULL
            )
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE public.person_name_forms
            DROP CONSTRAINT person_name_forms_split,
            DROP COLUMN last_name_normalized,
            DROP COLUMN first_name_normalized
    """)
