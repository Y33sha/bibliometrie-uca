"""Suppression des rattachements figés : table contributions, source_contributions.person_id et resolution_mode

Revision ID: 2d9f6b3e8a14
Revises: 6a2f8d4b9c31
Create Date: 2026-10-24 23:00:00.000000

La personne d'une contribution et son mode de rattachement sont portés par `source_contribution_groups`. La table `contributions` et les colonnes `person_id` et `resolution_mode` de `source_contributions` n'ont plus d'écrivain : elles disparaissent, avec leurs index, leur statistique et l'énumération `resolution_mode`.

Les épinglages d'un groupe dont les contributions sources sont épinglées à des personnes différentes sont supprimés : le rattachement des groupes redécide ces groupes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2d9f6b3e8a14"
down_revision: str | Sequence[str] | None = "6a2f8d4b9c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        WITH conflicting AS (
            SELECT gm.group_id
            FROM publications.source_contribution_group_members gm
            JOIN persons.confirmed_source_contributions c
              ON c.source_contribution_id = gm.source_contribution_id
            GROUP BY gm.group_id
            HAVING count(DISTINCT c.person_id) > 1
        )
        DELETE FROM persons.confirmed_source_contributions c
        USING publications.source_contribution_group_members gm
        WHERE gm.source_contribution_id = c.source_contribution_id
          AND gm.group_id IN (SELECT group_id FROM conflicting);

        DROP TABLE publications.contributions;
        DROP STATISTICS IF EXISTS sources.source_authorships_orphan_perimeter;
        ALTER TABLE sources.source_contributions
            DROP COLUMN person_id,
            DROP COLUMN resolution_mode;
        DROP TYPE public.resolution_mode;
    """)


def downgrade() -> None:
    """Irréversible : les rattachements figés et les épinglages contradictoires supprimés ne se reconstituent pas."""
    raise NotImplementedError(
        "La montée supprime les rattachements figés et des épinglages ; la descente n'a pas de quoi les rétablir."
    )
