"""source_authorship_structures : table de jointure → MATERIALIZED VIEW

`source_authorship_structures` (SAS) est entièrement dérivée :
`source_authorship_addresses ⋈ address_structures`, filtré par la clôture du
périmètre d'affiliation (`perimeter_structures`, sélectionné via la config
`perimeter_affiliations`) et par `address_structures.is_confirmed`. Le build
impératif (INSERT par source en `populate_affiliations`, purge full, resync
chirurgical admin) est remplacé par un `MATERIALIZED VIEW` rafraîchi.

Le filtre périmètre cessait d'être exprimable en SQL déclaratif tant que la
clôture vivait dans un paramètre Python ; `perimeter_structures` (matérialisée)
la fournit comme relation joignable. SAS ne porte aucun état natif.

`authorship_structures` (déjà matview, dérivée de SAS) est recréée par-dessus :
matview-sur-matview, rafraîchie dans l'ordre `perimeter_structures → SAS →
authorship_structures`.

Index sur chaque matview :
- unique `(…, structure_id)` — requis pour `REFRESH … CONCURRENTLY`.
- `(structure_id)` — filtrage labo des consommateurs.

Plus de FK : le `ON DELETE CASCADE` depuis `source_authorships` est remplacé par
le refresh (liens d'une SA supprimée inertes jusqu'au prochain refresh).

Revision ID: e8f1a3c5d7b9
Revises: d7e9c2a4b6f8
Create Date: 2026-06-03 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8f1a3c5d7b9"
down_revision: str | Sequence[str] | None = "d7e9c2a4b6f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SAS_SELECT = """
SELECT DISTINCT saa.source_authorship_id, ps.structure_id
FROM source_authorship_addresses saa
JOIN address_structures ast ON ast.address_id = saa.address_id
JOIN perimeter_structures ps ON ps.structure_id = ast.structure_id
WHERE ast.is_confirmed IS DISTINCT FROM FALSE
  AND ps.perimeter_id = (
      SELECT id FROM perimeters
      WHERE code = (SELECT value #>> '{}' FROM config WHERE key = 'perimeter_affiliations')
  )
"""

_AUS_SELECT = """
SELECT DISTINCT sa.authorship_id, sas.structure_id
FROM source_authorship_structures sas
JOIN source_authorships sa ON sa.id = sas.source_authorship_id
WHERE sa.authorship_id IS NOT NULL
"""


def _create_authorship_structures_matview() -> None:
    op.execute(f"CREATE MATERIALIZED VIEW authorship_structures AS {_AUS_SELECT} WITH DATA")
    op.execute(
        "CREATE UNIQUE INDEX authorship_structures_pkey "
        "ON authorship_structures (authorship_id, structure_id)"
    )
    op.execute(
        "CREATE INDEX idx_authorship_structures_structure_id "
        "ON authorship_structures (structure_id)"
    )


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW authorship_structures")
    op.execute("DROP TABLE source_authorship_structures")

    op.execute(f"CREATE MATERIALIZED VIEW source_authorship_structures AS {_SAS_SELECT} WITH DATA")
    op.execute(
        "CREATE UNIQUE INDEX source_authorship_structures_pkey "
        "ON source_authorship_structures (source_authorship_id, structure_id)"
    )
    op.execute(
        "CREATE INDEX idx_source_authorship_structures_structure_id "
        "ON source_authorship_structures (structure_id)"
    )

    _create_authorship_structures_matview()


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW authorship_structures")
    op.execute("DROP MATERIALIZED VIEW source_authorship_structures")

    op.execute("""
        CREATE TABLE source_authorship_structures (
            source_authorship_id integer NOT NULL,
            structure_id integer NOT NULL,
            CONSTRAINT source_authorship_structures_pkey
                PRIMARY KEY (source_authorship_id, structure_id),
            CONSTRAINT source_authorship_structures_source_authorship_id_fkey
                FOREIGN KEY (source_authorship_id) REFERENCES source_authorships(id) ON DELETE CASCADE,
            CONSTRAINT source_authorship_structures_structure_id_fkey
                FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE CASCADE
        )
    """)
    op.execute(
        "CREATE INDEX idx_source_authorship_structures_structure_id "
        "ON source_authorship_structures (structure_id)"
    )
    op.execute(
        f"INSERT INTO source_authorship_structures (source_authorship_id, structure_id) {_SAS_SELECT}"
    )

    _create_authorship_structures_matview()
