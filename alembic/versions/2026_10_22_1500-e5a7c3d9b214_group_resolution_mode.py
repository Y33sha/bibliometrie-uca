"""Enum group_resolution_mode pour source_contribution_groups.resolution_mode, renseigné avec person_id

Revision ID: e5a7c3d9b214
Revises: f1b5d8a3c726
Create Date: 2026-10-22 15:00:00.000000

Le mode d'un groupe nomme le signal qui l'a rattaché à sa personne : décision manuelle, ORCID, compte HAL, IdRef, forme de nom, initiales compatibles. Une contrainte lie le mode à la personne.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a7c3d9b214"
down_revision: str | Sequence[str] | None = "f1b5d8a3c726"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE public.group_resolution_mode AS ENUM"
        " ('manual', 'orcid', 'hal_person_id', 'idref', 'name', 'compatible_name')"
    )
    op.execute("""
        UPDATE publications.source_contribution_groups
        SET person_id = NULL, resolution_mode = NULL
        WHERE person_id IS NOT NULL OR resolution_mode IS NOT NULL
    """)
    op.execute("""
        ALTER TABLE publications.source_contribution_groups
        ALTER COLUMN resolution_mode TYPE public.group_resolution_mode USING NULL
    """)
    op.execute("""
        ALTER TABLE publications.source_contribution_groups
        ADD CONSTRAINT source_contribution_groups_resolution_mode_with_person
        CHECK ((person_id IS NULL) = (resolution_mode IS NULL))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE publications.source_contribution_groups
        DROP CONSTRAINT source_contribution_groups_resolution_mode_with_person
    """)
    op.execute("""
        ALTER TABLE publications.source_contribution_groups
        ALTER COLUMN resolution_mode TYPE public.resolution_mode USING NULL
    """)
    op.execute("DROP TYPE public.group_resolution_mode")
