"""publishers : retrait de la colonne `doi_prefix`

Concept mono-valeur remplacé par la table `doi_prefixes` (many-to-one : un publisher peut avoir N préfixes). Le mapping est désormais porté par `doi_prefixes.publisher_id`, plus par cette colonne.

Cette migration suit le commit qui retire les consommateurs (API/UI/DTOs/aggregate) ; les éventuelles données en `doi_prefix` sont déjà couvertes par `doi_prefixes` après seed initial + phase pipeline `resolve_doi_prefixes`.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-19 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("idx_publishers_doi_prefix", table_name="publishers")
    op.drop_column("publishers", "doi_prefix")


def downgrade() -> None:
    op.execute("ALTER TABLE publishers ADD COLUMN doi_prefix text")
    op.execute(
        """
        CREATE INDEX idx_publishers_doi_prefix ON publishers (doi_prefix)
        WHERE doi_prefix IS NOT NULL
        """
    )
