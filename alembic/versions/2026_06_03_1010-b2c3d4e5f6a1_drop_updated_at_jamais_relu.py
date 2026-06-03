"""drop updated_at jamais relu (audit : seul source_publications/publications le consomme)

`updated_at` était posé à la main (`= now()`) sur ces tables mais **jamais
relu** : ni SELECT, ni ORDER BY, ni comparaison, ni exposition frontend. Seul
le couple `source_publications.updated_at > publications.updated_at` (staleness
du refresh) le consomme réellement — ces deux-là sont conservés.

Retiré sur : authorships, config, journals, persons, persons_rh, publishers.
Les écritures `updated_at = now()` correspondantes sont supprimées des repos
dans le même commit. `config.updated_at` était sérialisé dans le DTO
`ConfigItem` mais jamais affiché ; remplacé par `created_at`.

Revision ID: b2c3d4e5f6a1
Revises: c1a2d3e4f5b6
Create Date: 2026-06-03 10:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a1"
down_revision: str | Sequence[str] | None = "c1a2d3e4f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("authorships", "config", "journals", "persons", "persons_rh", "publishers")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN updated_at")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN updated_at timestamptz DEFAULT now()")
