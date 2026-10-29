"""Index hash sur les titres normalisés

Revision ID: d9b3e6a1f5c2
Revises: c7e2a9f4b1d8
Create Date: 2026-10-29 14:00:00.000000

Un index btree refuse une entrée de plus de 2 704 octets, donc un titre long fait échouer l'écriture de sa ligne. Un index hash stocke le hash de la valeur, sans limite de longueur. Les requêtes sur `title_normalized` sont des égalités, qu'un index hash sert.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9b3e6a1f5c2"
down_revision: str | Sequence[str] | None = "c7e2a9f4b1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (schéma, table, index btree, colonnes de l'index btree)
_BTREE_INDEXES = (
    (
        "sources",
        "source_records",
        "idx_source_records_metadata_block",
        "title_normalized, publication_year, doc_type",
    ),
    (
        "publications",
        "publications",
        "idx_publications_titlenorm_year",
        "title_normalized, publication_year",
    ),
    ("publishing", "serials", "idx_serials_titlenorm", "title_normalized"),
    ("publishing", "monographs", "idx_monographs_title_normalized", "title_normalized"),
)


def upgrade() -> None:
    for schema, table, btree, _columns in _BTREE_INDEXES:
        op.execute(f"DROP INDEX {schema}.{btree}")
        op.execute(
            f"CREATE INDEX idx_{table}_title_normalized ON {schema}.{table} USING hash (title_normalized)"
        )


def downgrade() -> None:
    for schema, table, btree, columns in _BTREE_INDEXES:
        op.execute(f"DROP INDEX {schema}.idx_{table}_title_normalized")
        op.execute(f"CREATE INDEX {btree} ON {schema}.{table} USING btree ({columns})")
