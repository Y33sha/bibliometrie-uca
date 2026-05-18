"""addresses : index btree sur `normalized_text` pour la propagation pays

L'index GIN trgm existant (`idx_addresses_normalized_text_trgm`) ne sert que pour la recherche fuzzy (ILIKE). Le JOIN par égalité utilisé dans `propagate_countries_across_similar_addresses` (`WHERE a2.normalized_text = a1.normalized_text`) ne peut pas l'exploiter et tombait en seqscan × seqscan O(n²) sur 475 K adresses — plusieurs minutes par batch, 504 garanti.

Un index btree dédié rend ce JOIN O(log n).

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-18 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_addresses_normalized_text",
        "addresses",
        ["normalized_text"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_addresses_normalized_text", table_name="addresses")
