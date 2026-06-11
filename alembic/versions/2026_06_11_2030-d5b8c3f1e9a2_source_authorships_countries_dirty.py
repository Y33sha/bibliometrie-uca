"""source_authorships.countries_dirty : refresh pays incrémental

Le recalcul de `source_authorships.countries` (puis `source_publications` et
`publications`) se faisait intégralement à chaque run (~7-15M lignes, plusieurs
minutes) même quand rien ne changeait. On le rend incrémental via un flag
`countries_dirty` :
  - nouveaux `sa` (normalize) → `true` par défaut ;
  - `sa` dont une adresse gagne un pays (detect / institution) → marqués `true` ;
  - le refresh ne recalcule que les `sa` `countries_dirty`, puis remet à `false`.

Les `sa` existants sont posés à `false` (cache à jour au moment de la migration ;
le full refresh CLI reste disponible pour forcer un recalcul complet). L'index
partiel rend le repérage des `sa` dirty sub-seconde quand ils sont peu nombreux.

Revision ID: d5b8c3f1e9a2
Revises: b8e3a1f6d4c2
Create Date: 2026-06-11 20:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5b8c3f1e9a2"
down_revision: str | Sequence[str] | None = "b8e3a1f6d4c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD avec défaut false (existant = à jour), puis bascule du défaut à true
    # (nouveaux sa = à recalculer). L'index partiel reste vide tant que rien
    # n'est dirty.
    op.execute(
        "ALTER TABLE source_authorships ADD COLUMN countries_dirty boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE source_authorships ALTER COLUMN countries_dirty SET DEFAULT true")
    op.execute(
        "CREATE INDEX idx_sa_countries_dirty ON source_authorships (source_publication_id) "
        "WHERE countries_dirty"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_sa_countries_dirty")
    op.execute("ALTER TABLE source_authorships DROP COLUMN countries_dirty")
