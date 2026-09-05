"""Réduit `structure_relations` aux tutelles et la renomme `structure_tutelles`

Seule la tutelle porte une conséquence : sa clôture récursive définit le périmètre. Le partenariat ne servait qu'à répliquer une information du référentiel ROR, et la validation du graphe le comptait pourtant comme une arête — la marche d'ancêtres qui refuse les cycles ne distinguait pas les deux types, si bien qu'un partenariat pouvait faire refuser une tutelle.

Revision ID: c9d2f5b81a37
Revises: b3c7e94a2f18
Create Date: 2026-09-05 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9d2f5b81a37"
down_revision: str | Sequence[str] | None = "b3c7e94a2f18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM structure_relations WHERE relation_type <> 'est_tutelle_de'")
    # La suppression de la colonne emporte l'unique qui la portait.
    op.execute("ALTER TABLE structure_relations DROP COLUMN relation_type")

    op.execute("ALTER TABLE structure_relations RENAME TO structure_tutelles")
    op.execute("ALTER SEQUENCE structure_relations_id_seq RENAME TO structure_tutelles_id_seq")
    op.execute(
        "ALTER TABLE structure_tutelles "
        "RENAME CONSTRAINT structure_relations_pkey TO structure_tutelles_pkey"
    )
    op.execute(
        "ALTER TABLE structure_tutelles RENAME CONSTRAINT "
        "structure_relations_no_self_reference TO structure_tutelles_no_self_reference"
    )
    op.execute(
        "ALTER TABLE structure_tutelles RENAME CONSTRAINT "
        "structure_relations_parent_id_fkey TO structure_tutelles_parent_id_fkey"
    )
    op.execute(
        "ALTER TABLE structure_tutelles RENAME CONSTRAINT "
        "structure_relations_child_id_fkey TO structure_tutelles_child_id_fkey"
    )
    op.execute("ALTER INDEX idx_struct_rel_parent RENAME TO idx_struct_tut_parent")
    op.execute("ALTER INDEX idx_struct_rel_child RENAME TO idx_struct_tut_child")

    op.execute(
        "ALTER TABLE structure_tutelles "
        "ADD CONSTRAINT structure_tutelles_parent_id_child_id_key UNIQUE (parent_id, child_id)"
    )


def downgrade() -> None:
    """Irréversible : les partenariats supprimés ne se reconstituent pas."""
    raise NotImplementedError(
        "La montée supprime les lignes de partenariat ; la descente n'a pas de quoi les rétablir."
    )
