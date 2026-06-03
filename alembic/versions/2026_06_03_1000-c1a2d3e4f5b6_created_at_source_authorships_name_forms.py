"""created_at : source_authorships, person_name_forms, structure_relations, config

Ajout de `created_at` (provenance/debug) là où il est utile et manquant :
- `source_authorships` (symétrie avec `source_publications` ; la ligne est
  supprimée/recréée au réimport, donc `created_at` reflète le dernier import) ;
- `person_name_forms` (les autres `*_name_forms` l'ont déjà) ;
- `structure_relations` (audit des arêtes de hiérarchie curées à la main) ;
- `config` (provenance d'une clé ; en remplacement de `updated_at` jamais
  relu, retiré dans la migration suivante).

`DEFAULT now()` est évalué une fois au moment du ALTER (PG ≥ 11, fast-default :
pas de réécriture de table) ; les lignes existantes prennent l'horodatage de la
migration.

Revision ID: c1a2d3e4f5b6
Revises: d5e8b3a1f6c4
Create Date: 2026-06-03 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1a2d3e4f5b6"
down_revision: str | Sequence[str] | None = "d5e8b3a1f6c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("source_authorships", "person_name_forms", "structure_relations", "config")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN created_at timestamptz DEFAULT now()")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN created_at")
