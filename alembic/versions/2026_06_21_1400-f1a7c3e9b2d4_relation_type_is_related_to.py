"""relation_type : ajoute la valeur is_related_to

Relation symétrique « apparentée, type à qualifier », posée par le signal #2 (clés de confirmation
partagées entre publications à DOI distincts) quand le couple de doc_type ne permet pas encore
d'inférer une relation précise. Correspond à `domain.publications.relations.RelationType.IS_RELATED_TO`.

Revision ID: f1a7c3e9b2d4
Revises: d3f8b1a6c4e2
Create Date: 2026-06-21 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a7c3e9b2d4"
down_revision: str | Sequence[str] | None = "d3f8b1a6c4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.relation_type ADD VALUE IF NOT EXISTS 'is_related_to'")


def downgrade() -> None:
    # PostgreSQL ne sait pas retirer une valeur d'un type ENUM (pas de DROP VALUE). Le rollback
    # exigerait de recréer le type sans la valeur et de réécrire toutes les colonnes qui l'utilisent ;
    # on l'omet volontairement (no-op), la valeur orpheline étant inoffensive.
    pass
