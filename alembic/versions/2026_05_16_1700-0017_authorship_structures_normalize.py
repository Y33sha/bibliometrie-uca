"""authorships + source_authorships : sortir `structure_ids[]` en tables de jointure

Phase 2+3 (fusionnées) du chantier `DATA_jointures-many-to-many.md` :
les colonnes array `authorships.structure_ids` et
`source_authorships.structure_ids` deviennent les tables de jointure
naturelles `authorship_structures (authorship_id, structure_id)` et
`source_authorship_structures (source_authorship_id, structure_id)`,
avec FK `ON DELETE CASCADE` des deux côtés et PK composite.

Backfill atomique : `unnest(structure_ids)` croisé avec `structures`
pour filtrer les ids morts (Postgres ne supportait pas de FK sur
élément d'array — d'où la cascade applicative `purge_structure_id_from_arrays`
qui disparaît en parallèle de cette migration).

Volumes attendus (snapshot 2026-05-15) :
- `authorship_structures` ≈ 196 K rows depuis 94 K authorships non vides
  (sur 151 K total, 62 % renseignés).
- `source_authorship_structures` ≈ 338 K rows depuis 173 K source_authorships
  non vides (sur 8.1 M total, 2 % renseignés).

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-16 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE authorship_structures (
            authorship_id integer NOT NULL REFERENCES authorships(id) ON DELETE CASCADE,
            structure_id integer NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
            PRIMARY KEY (authorship_id, structure_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_authorship_structures_structure_id "
        "ON authorship_structures (structure_id)"
    )
    op.execute(
        """
        CREATE TABLE source_authorship_structures (
            source_authorship_id integer NOT NULL REFERENCES source_authorships(id) ON DELETE CASCADE,
            structure_id integer NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
            PRIMARY KEY (source_authorship_id, structure_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_source_authorship_structures_structure_id "
        "ON source_authorship_structures (structure_id)"
    )

    # Backfill avec JOIN structures pour filtrer les ids morts (FK sur
    # élément d'array impossible historiquement → des ids orphelins
    # peuvent traîner dans les arrays).
    op.execute(
        """
        INSERT INTO authorship_structures (authorship_id, structure_id)
        SELECT a.id, sid
        FROM authorships a
        CROSS JOIN LATERAL unnest(a.structure_ids) AS sid
        JOIN structures s ON s.id = sid
        WHERE a.structure_ids IS NOT NULL AND cardinality(a.structure_ids) > 0
        """
    )
    op.execute(
        """
        INSERT INTO source_authorship_structures (source_authorship_id, structure_id)
        SELECT sa.id, sid
        FROM source_authorships sa
        CROSS JOIN LATERAL unnest(sa.structure_ids) AS sid
        JOIN structures s ON s.id = sid
        WHERE sa.structure_ids IS NOT NULL AND cardinality(sa.structure_ids) > 0
        """
    )

    op.execute("ALTER TABLE authorships DROP COLUMN structure_ids")
    op.execute("ALTER TABLE source_authorships DROP COLUMN structure_ids")


def downgrade() -> None:
    op.execute("ALTER TABLE authorships ADD COLUMN structure_ids integer[]")
    op.execute("ALTER TABLE source_authorships ADD COLUMN structure_ids integer[]")
    op.execute(
        """
        UPDATE authorships a
        SET structure_ids = sub.ids
        FROM (
            SELECT authorship_id, array_agg(structure_id ORDER BY structure_id) AS ids
            FROM authorship_structures
            GROUP BY authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
        """
    )
    op.execute(
        """
        UPDATE source_authorships sa
        SET structure_ids = sub.ids
        FROM (
            SELECT source_authorship_id, array_agg(structure_id ORDER BY structure_id) AS ids
            FROM source_authorship_structures
            GROUP BY source_authorship_id
        ) sub
        WHERE sa.id = sub.source_authorship_id
        """
    )
    op.execute("DROP TABLE source_authorship_structures")
    op.execute("DROP TABLE authorship_structures")
