"""drop source_persons and source_structures

Phase 4 (finale) du chantier `DATA_simplify-source-tables.md`. La
MetaData et le code applicatif sont déjà alignés sur l'état post-DROP
depuis les commits Phase 3 — cette migration amène la DB à les
rejoindre.

Sur `source_authorships` :
- DROP COLUMN `source_person_id` (toujours NULL depuis les normalizers
  Phase 3 — la FK et le UNIQUE qui la référençaient tombent avec).
- DROP COLUMN `source_struct_ids` (remplacée par `source_structures`
  TEXT[] depuis le chantier Phase 1/2).
- Bascule UNIQUE : `(source_publication_id, source_person_id,
  author_position)` → `(source_publication_id, author_position)`
  (nouveau nom `source_authorships_pub_pos_key`).
- DROP INDEX `idx_sa_source_person` et `idx_sa_orphan_perimeter`
  (toutes deux liées à `source_person_id`).

Puis DROP TABLE `source_persons` et `source_structures`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12 16:54:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "source_authorships_source_person_id_fkey",
        "source_authorships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "source_authorships_pub_person_pos_key",
        "source_authorships",
        type_="unique",
    )
    op.drop_index("idx_sa_source_person", "source_authorships")
    op.drop_index("idx_sa_orphan_perimeter", "source_authorships")
    op.drop_column("source_authorships", "source_person_id")
    op.drop_column("source_authorships", "source_struct_ids")
    op.create_unique_constraint(
        "source_authorships_pub_pos_key",
        "source_authorships",
        ["source_publication_id", "author_position"],
    )

    op.drop_table("source_persons")
    op.drop_table("source_structures")


def downgrade() -> None:
    raise NotImplementedError(
        "Migration non réversible : les données de `source_persons` et "
        "`source_structures` sont perdues définitivement. Revenir au baseline "
        "si nécessaire."
    )
