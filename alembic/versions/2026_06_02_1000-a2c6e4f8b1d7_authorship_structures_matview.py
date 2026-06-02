"""authorship_structures : table de jointure → MATERIALIZED VIEW

`authorship_structures` est entièrement dérivée : union des
`source_authorship_structures` des `source_authorships` reliées à une
authorship canonique (`authorship_id IS NOT NULL`). Le rebuild impératif
(INSERT add-only en daily/weekly + TRUNCATE en full + recompute ciblés admin)
est remplacé par un `MATERIALIZED VIEW` rafraîchi (`REFRESH … CONCURRENTLY`).

L'incrémental add-only laissait des liens obsolètes entre deux full rebuilds ;
la matview est exacte à chaque refresh. Le filtre `v_active_publications` du
build est redondant (`authorship_id IS NOT NULL` implique une authorship, donc
une publication active) et coûteux (482 k nested loops) — la définition s'en
passe ; les ~10 liens de pubs inactives résiduelles sont inertes en aval
(les consommateurs joignent les publications actives).

Index :
- unique `(authorship_id, structure_id)` — requis pour `REFRESH CONCURRENTLY`.
- `(structure_id)` — filtrage labo (consommateurs `EXISTS … structure_id = ANY`).

La matview n'a pas de FK : le `ON DELETE CASCADE` de `authorship_id` est
remplacé par le refresh (les liens d'une authorship supprimée disparaissent au
prochain refresh ; inertes entre-temps, les lectures inner-joignent `authorships`).

Revision ID: a2c6e4f8b1d7
Revises: f3b6d9c1a8e2
Create Date: 2026-06-02 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2c6e4f8b1d7"
down_revision: str | Sequence[str] | None = "f3b6d9c1a8e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MATVIEW_SELECT = """
SELECT DISTINCT sa.authorship_id, sas.structure_id
FROM source_authorship_structures sas
JOIN source_authorships sa ON sa.id = sas.source_authorship_id
WHERE sa.authorship_id IS NOT NULL
"""


def upgrade() -> None:
    op.execute("DROP TABLE authorship_structures CASCADE")
    op.execute(f"CREATE MATERIALIZED VIEW authorship_structures AS {_MATVIEW_SELECT} WITH DATA")
    op.execute(
        "CREATE UNIQUE INDEX authorship_structures_pkey "
        "ON authorship_structures (authorship_id, structure_id)"
    )
    op.execute(
        "CREATE INDEX idx_authorship_structures_structure_id "
        "ON authorship_structures (structure_id)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW authorship_structures")
    op.execute("""
        CREATE TABLE authorship_structures (
            authorship_id integer NOT NULL,
            structure_id integer NOT NULL,
            CONSTRAINT authorship_structures_pkey PRIMARY KEY (authorship_id, structure_id),
            CONSTRAINT authorship_structures_authorship_id_fkey
                FOREIGN KEY (authorship_id) REFERENCES authorships(id) ON DELETE CASCADE,
            CONSTRAINT authorship_structures_structure_id_fkey
                FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE CASCADE
        )
    """)
    op.execute(
        "CREATE INDEX idx_authorship_structures_structure_id "
        "ON authorship_structures (structure_id)"
    )
    op.execute(f"INSERT INTO authorship_structures (authorship_id, structure_id) {_MATVIEW_SELECT}")
