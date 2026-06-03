"""perimeter_structures : clôture transitive du périmètre matérialisée

Matérialise, par périmètre, la clôture récursive (`est_tutelle_de`) de
`perimeters.structure_ids`. Fournit la clôture comme relation joignable —
prérequis pour passer `source_authorship_structures` en matview (cf.
`DATA_perimeter-materialise`) — et sert directement l'UI/audit (« structures
d'un périmètre »).

Table dénormalisée maintenue explicitement : refresh en début de phase
`affiliations` (`refresh_perimeter_structures`) et à chaque édition admin de
`perimeters.structure_ids` / `structure_relations`. FK CASCADE des deux côtés.

Le remplissage initial reproduit la CTE de `get_perimeter_structure_ids`
(racines = `perimeters.structure_ids`, descente `est_tutelle_de` uniquement).
Duplication SQL assumée avec `refresh_perimeter_structures`.

Revision ID: d7e9c2a4b6f8
Revises: b2c3d4e5f6a1
Create Date: 2026-06-03 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7e9c2a4b6f8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FILL = """
INSERT INTO perimeter_structures (perimeter_id, structure_id)
WITH RECURSIVE descendants AS (
    SELECT p.id AS perimeter_id, s.structure_id
    FROM perimeters p
    CROSS JOIN LATERAL unnest(p.structure_ids) AS s(structure_id)
    UNION
    SELECT d.perimeter_id, sr.child_id
    FROM descendants d
    JOIN structure_relations sr ON sr.parent_id = d.structure_id
    WHERE sr.relation_type = 'est_tutelle_de'
)
SELECT DISTINCT d.perimeter_id, d.structure_id
FROM descendants d
WHERE EXISTS (SELECT 1 FROM structures st WHERE st.id = d.structure_id)
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE perimeter_structures (
            perimeter_id integer NOT NULL REFERENCES perimeters(id) ON DELETE CASCADE,
            structure_id integer NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
            CONSTRAINT perimeter_structures_pkey PRIMARY KEY (perimeter_id, structure_id)
        )
    """)
    op.execute("CREATE INDEX idx_ps_structure_id ON perimeter_structures (structure_id)")
    op.execute(_FILL)


def downgrade() -> None:
    op.execute("DROP TABLE perimeter_structures")
