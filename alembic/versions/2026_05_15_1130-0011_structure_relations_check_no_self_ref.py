"""structure_relations : CHECK no self-reference

Défense en profondeur côté DB. L'invariant principal (auto-référence +
cycles) vit dans `domain/structures/relations.py:check_can_create_relation`,
appelé par `application/structures.py:create_relation`. Cette contrainte
SQL bloque les chemins d'écriture qui contourneraient le service
(scripts ad hoc, manipulations manuelles).

Pas de CHECK pour les cycles : Postgres ne sait pas valider un invariant
récursif sur l'ensemble du graphe via un CHECK constraint. La validation
reste applicative.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-15 11:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "structure_relations_no_self_reference",
        "structure_relations",
        "parent_id <> child_id",
    )


def downgrade() -> None:
    op.drop_constraint(
        "structure_relations_no_self_reference",
        "structure_relations",
        type_="check",
    )
