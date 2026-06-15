"""source_publications.keys_dirty : drapeau de réconciliation de composante

Déclencheur de la réconciliation des composantes (`recompute_component`) : une SP est marquée `keys_dirty = true` dès que ses clés de confirmation effectives changent (insert / re-normalize, correction de métadonnées qui nulle ou corrige une clé, rattachement par l'assignation). La passe de réconciliation balaie les SP dirty, recalcule leur composante connexe (SP reliées par clé partagée), réconcilie les publications matérialisées (une par composante), puis efface le drapeau.

`DEFAULT true` : le stock existant est entièrement dirty, soumis à la première réconciliation complète. Index partiel sur les SP dirty (la passe ne lit qu'elles, fraction décroissante du stock après le premier balayage).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c4e9f2b1d6"
down_revision: str | Sequence[str] | None = "cff75ac2ea58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_publications",
        sa.Column("keys_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "idx_source_pubs_keys_dirty",
        "source_publications",
        ["keys_dirty"],
        postgresql_where=sa.text("keys_dirty"),
    )


def downgrade() -> None:
    op.drop_index("idx_source_pubs_keys_dirty", table_name="source_publications")
    op.drop_column("source_publications", "keys_dirty")
