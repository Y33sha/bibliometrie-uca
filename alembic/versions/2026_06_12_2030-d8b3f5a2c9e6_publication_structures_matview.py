"""publication_structures : matview publi↔structure dédupliquée (facette labos)

La facette labos comptait les publications par labo via une jointure 4 tables
(authorships × authorship_structures × structures × publications) + un
`COUNT(DISTINCT publication_id)` par labo → tri externe sur disque, ~1,9 s, le
long pole de la page publications (les autres facettes etant rapides depuis le
narrow-table).

On materialise le lien publi↔structure dedoublonne. La facette devient alors
`COUNT(*)` par structure sur cette matview jointe a `publications` (filtre
perimetre) et `structures` (filtre labo) : plus de jointure authorships ni de
DISTINCT/tri. ~8 Mo. Rafraichie dans le pipeline (apres authorship_structures,
dont elle derive), comme les autres matviews de structures.

Revision ID: d8b3f5a2c9e6
Revises: c2e5a8f1d4b7
Create Date: 2026-06-12 20:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d8b3f5a2c9e6"
down_revision: str | Sequence[str] | None = "c2e5a8f1d4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW publication_structures AS
            SELECT DISTINCT a.publication_id, aus.structure_id
            FROM authorships a
            JOIN authorship_structures aus ON aus.authorship_id = a.id
        WITH NO DATA
    """)
    # Index unique requis par REFRESH ... CONCURRENTLY ; sert aussi le join publi.
    op.execute("""
        CREATE UNIQUE INDEX publication_structures_pub_struct
        ON publication_structures (publication_id, structure_id)
    """)
    # GROUP BY structure_id de la facette.
    op.execute("""
        CREATE INDEX idx_publication_structures_structure
        ON publication_structures (structure_id)
    """)
    op.execute("REFRESH MATERIALIZED VIEW publication_structures")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS publication_structures")
