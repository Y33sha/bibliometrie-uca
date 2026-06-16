"""source_publications.title_normalized : forme normalisée du titre + index GIN trgm

Matérialise la forme normalisée du titre (`clean_publication_title` + `normalize_text`,
cf. `domain.publications.metadata.normalized_title`) que le matcher calcule aujourd'hui à
la volée. Sert le blocking / la dédup métadonnées et la comparaison floue chapitre/chapitre
(d'où l'index GIN `gin_trgm_ops` pour `similarity()`).

Colonne nullable : peuplée par la passe `materialize_title_normalized` (auto-backfill au
premier run, puis incrémentale sur les SP non encore normalisées — `title` est INSERT-only,
donc `title_normalized` ne devient jamais périmé).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cff75ac2ea58"
down_revision: str | Sequence[str] | None = "1278fb0fe5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_publications", sa.Column("title_normalized", sa.Text(), nullable=True))
    op.create_index(
        "idx_source_pubs_title_normalized_trgm",
        "source_publications",
        ["title_normalized"],
        postgresql_using="gin",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "idx_source_pubs_title_normalized_trgm",
        table_name="source_publications",
        postgresql_using="gin",
    )
    op.drop_column("source_publications", "title_normalized")
