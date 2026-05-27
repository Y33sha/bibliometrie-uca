"""doc_type : ajouter la valeur d'enum 'media'

Type de document pour les interventions média (libellé FR « Intervention média »). Cible de la correction qui reclasse une publication dont la revue est de type `journal_type = media` : `journal.type = media ⇒ doc_type = media`.

Revision ID: 00da0bf27d36
Revises: c5d7e9f1a3b5
Create Date: 2026-05-27 20:35:07.803878
"""

from collections.abc import Sequence

from alembic import op

revision: str = "00da0bf27d36"
down_revision: str | Sequence[str] | None = "c5d7e9f1a3b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.doc_type ADD VALUE IF NOT EXISTS 'media'")


def downgrade() -> None:
    # Postgres ne permet pas `ALTER TYPE ... DROP VALUE` directement ; pour
    # rollback il faudrait recréer l'enum sans la valeur et basculer la
    # colonne via cast (cf. migration 0020 sur structure_type). Cas peu
    # probable ici — non implémenté.
    raise NotImplementedError("Postgres ne supporte pas le DROP VALUE sur enum")
