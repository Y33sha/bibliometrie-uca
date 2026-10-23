"""Files d'attente sans clé étrangère

Revision ID: 579f75a9a1f6
Revises: caea1a0f3768
Create Date: 2026-10-23 22:00:00.000000

La vérification d'une clé étrangère verrouille la ligne référencée à chaque marquage. Un identifiant dont la ligne est supprimée reste en file jusqu'au passage de la tâche qui lit la file : elle l'ignore, puis supprime son marquage.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "579f75a9a1f6"
down_revision: str | Sequence[str] | None = "caea1a0f3768"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# File, table traitée.
_QUEUES = (
    ("source_contribution_countries_queue", "sources.source_contributions"),
    ("address_countries_queue", "structures.addresses"),
    ("address_candidates_queue", "structures.addresses"),
    ("publication_contributions_queue", "publications.publications"),
    ("source_record_keys_queue", "sources.source_records"),
    ("source_contribution_group_attributes_queue", "publications.source_contribution_groups"),
)


def upgrade() -> None:
    for queue, _ in _QUEUES:
        op.execute(f"ALTER TABLE queues.{queue} DROP CONSTRAINT {queue}_id_fkey")


def downgrade() -> None:
    for queue, table in _QUEUES:
        op.execute(f"""
            DELETE FROM queues.{queue} q
            WHERE NOT EXISTS (SELECT 1 FROM {table} t WHERE t.id = q.id)
        """)
        op.execute(f"""
            ALTER TABLE queues.{queue} ADD CONSTRAINT {queue}_id_fkey
                FOREIGN KEY (id) REFERENCES {table} (id) ON DELETE CASCADE
        """)
