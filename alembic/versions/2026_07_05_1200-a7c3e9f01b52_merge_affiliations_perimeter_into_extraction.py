"""Fusionne le périmètre d'affiliation dans celui d'extraction

La matview `source_authorship_structures` restreignait les structures reconnues dans les
affiliations au périmètre `perimeter_affiliations`. On part du principe qu'on reconnaît les
affiliations de toutes les structures qu'on interroge : elle lit désormais `perimeter_extraction`,
et la clé de config `perimeter_affiliations` est supprimée. Aucun effet fonctionnel aujourd'hui
(les deux périmètres valent la même valeur).

Comme le périmètre est inscrit dans le SQL de la matview, la bascule impose de redéfinir la
chaîne `source_authorship_structures → authorship_structures → publication_structures` (seule la
première change ; les deux suivantes sont recréées à l'identique car elles en dépendent). Les
matviews sont recréées `WITH DATA` : contenu inchangé, immédiatement requêtables, refresh
`CONCURRENTLY` du pipeline opérationnel ensuite.

Revision ID: a7c3e9f01b52
Revises: f4b2e6a09c81
Create Date: 2026-07-05 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c3e9f01b52"
down_revision: str | Sequence[str] | None = "f4b2e6a09c81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SAS_TEMPLATE = """
    CREATE MATERIALIZED VIEW source_authorship_structures AS
    SELECT DISTINCT saa.source_authorship_id, ps.structure_id
    FROM source_authorship_addresses saa
    JOIN address_structures ast ON ast.address_id = saa.address_id
    JOIN perimeter_structures ps ON ps.structure_id = ast.structure_id
    WHERE ast.is_confirmed IS DISTINCT FROM false
      AND ps.perimeter_id = (
          SELECT id FROM perimeters
          WHERE code = (SELECT value #>> '{{}}' FROM config WHERE key = '{perimeter_key}')
      )
    WITH DATA
"""

_DOWNSTREAM = """
    CREATE MATERIALIZED VIEW authorship_structures AS
    SELECT DISTINCT sa.authorship_id, sas.structure_id
    FROM source_authorship_structures sas
    JOIN source_authorships sa ON sa.id = sas.source_authorship_id
    WHERE sa.authorship_id IS NOT NULL
    WITH DATA;

    CREATE MATERIALIZED VIEW publication_structures AS
    SELECT DISTINCT a.publication_id, aus.structure_id
    FROM authorships a
    JOIN authorship_structures aus ON aus.authorship_id = a.id
    WITH DATA;
"""

_INDEXES = """
    CREATE UNIQUE INDEX source_authorship_structures_pkey
        ON source_authorship_structures (source_authorship_id, structure_id);
    CREATE INDEX idx_source_authorship_structures_structure_id
        ON source_authorship_structures (structure_id);
    CREATE UNIQUE INDEX authorship_structures_pkey
        ON authorship_structures (authorship_id, structure_id);
    CREATE INDEX idx_authorship_structures_structure_id
        ON authorship_structures (structure_id);
    CREATE UNIQUE INDEX publication_structures_pub_struct
        ON publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publication_structures (structure_id);
"""

_DROP_CHAIN = """
    DROP MATERIALIZED VIEW publication_structures;
    DROP MATERIALIZED VIEW authorship_structures;
    DROP MATERIALIZED VIEW source_authorship_structures;
"""


def upgrade() -> None:
    op.execute(_DROP_CHAIN)
    op.execute(_SAS_TEMPLATE.format(perimeter_key="perimeter_extraction"))
    op.execute(_DOWNSTREAM)
    op.execute(_INDEXES)
    op.execute("DELETE FROM config WHERE key = 'perimeter_affiliations'")


def downgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value, description) VALUES "
        "('perimeter_affiliations', '\"uca_wide\"', "
        "'Périmètre pour la résolution des affiliations (structure_ids sur authorships sources)')"
    )
    op.execute(_DROP_CHAIN)
    op.execute(_SAS_TEMPLATE.format(perimeter_key="perimeter_affiliations"))
    op.execute(_DOWNSTREAM)
    op.execute(_INDEXES)
