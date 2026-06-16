"""source_publications : index btree (title_normalized, pub_year, doc_type) pour le blocking métadonnée

La réconciliation joint les `source_publications` par **égalité** sur la clé de blocking `(title_normalized, pub_year, doc_type)` (tokens `thesis_meta` et `metadata_block`). L'unique index existant sur `title_normalized` est un **GIN trigram** (`gin_trgm_ops`), fait pour `similarity()` / `LIKE`, **inutile pour le `=` exact** : la jointure dégénérait en scan complet par SP dirty (hang sur ~100k SP). Ce btree composite sert l'égalité.

Composite : `title_normalized` en tête (sélectif), puis `pub_year` et `doc_type` (le reste de la clé de blocking). `max(length(title_normalized)) = 1639` au stock ⇒ sous la limite de taille de clé btree (~2700 octets), pas de risque d'« index row size exceeds maximum ».
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a9c1e7f3b2"
down_revision: str | Sequence[str] | None = "94c27bec8361"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_source_pubs_metadata_block",
        "source_publications",
        ["title_normalized", "pub_year", "doc_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_source_pubs_metadata_block", table_name="source_publications")
