"""addresses.countries_dirty : marquage gratuit du delta pour le refresh incrémental

Le marquage des `source_authorships` dirty (Phase précédente) coûtait cher quand
une adresse institutionnelle partagée par des milliers d'authorships changeait :
des centaines de milliers de `sa` réécrits juste pour poser un flag. On déplace
le signal sur l'**adresse** : `addresses.countries_dirty` est posé dans la même
requête que l'écriture de `countries` (ligne déjà réécrite → coût nul), et le
refresh **dérive** les `sa` concernés par un JOIN (lecture), sans marquage de masse.

Le flag `source_authorships.countries_dirty` reste, mais uniquement pour les
nouveaux `sa` (défaut `true` posé par normalize). Le refresh recalcule les `sa`
tels que `sa.countries_dirty` OU liés à une adresse `countries_dirty`.

Existant à `false` (cache à jour ; les adresses sans pays ne sont pas dirty).

Revision ID: f3a8d2c5e1b7
Revises: d5b8c3f1e9a2
Create Date: 2026-06-12 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a8d2c5e1b7"
down_revision: str | Sequence[str] | None = "d5b8c3f1e9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE addresses ADD COLUMN countries_dirty boolean NOT NULL DEFAULT false")
    op.execute("CREATE INDEX idx_addresses_countries_dirty ON addresses (id) WHERE countries_dirty")


def downgrade() -> None:
    op.execute("DROP INDEX idx_addresses_countries_dirty")
    op.execute("ALTER TABLE addresses DROP COLUMN countries_dirty")
