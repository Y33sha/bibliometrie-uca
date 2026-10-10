"""Le lien d'une signature à son authorship se lit par jointure

`source_authorships.authorship_id` recopiait le résultat d'une jointure : une authorship est définie par son couple (publication, personne), que la signature atteint par sa notice et sa personne. La colonne, sa clé étrangère et son index disparaissent. `authorship_structures` passe par la jointure ; `publication_structures`, qui en dépend, est recréée à l'identique. Les deux matviews sont recréées `WITH DATA`, puis le pipeline les rafraîchit `CONCURRENTLY`.

Revision ID: d2a7f4c9e815
Revises: c9f3b7e2d814
Create Date: 2026-10-10 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2a7f4c9e815"
down_revision: str | Sequence[str] | None = "c9f3b7e2d814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DROP_MATVIEWS = """
    DROP MATERIALIZED VIEW publication_structures;
    DROP MATERIALIZED VIEW authorship_structures;
"""

_AUTHORSHIP_STRUCTURES = """
    CREATE MATERIALIZED VIEW authorship_structures AS
    SELECT DISTINCT a.id AS authorship_id, sas.structure_id
    FROM source_authorship_structures sas
    JOIN source_authorships sa ON sa.id = sas.source_authorship_id
    JOIN source_publications sp ON sp.id = sa.source_publication_id
    JOIN authorships a ON a.publication_id = sp.publication_id AND a.person_id = sa.person_id
    WHERE NOT EXISTS (
        SELECT 1 FROM persons pe WHERE pe.id = a.person_id AND pe.exclusion IS NOT NULL
    )
    WITH DATA;
"""

_AUTHORSHIP_STRUCTURES_DOWNGRADE = """
    CREATE MATERIALIZED VIEW authorship_structures AS
    SELECT DISTINCT sa.authorship_id, sas.structure_id
    FROM source_authorship_structures sas
    JOIN source_authorships sa ON sa.id = sas.source_authorship_id
    JOIN authorships a ON a.id = sa.authorship_id
    WHERE NOT EXISTS (
        SELECT 1 FROM persons pe WHERE pe.id = a.person_id AND pe.exclusion IS NOT NULL
    )
    WITH DATA;
"""

_PUBLICATION_STRUCTURES_AND_INDEXES = """
    CREATE MATERIALIZED VIEW publication_structures AS
    SELECT DISTINCT a.publication_id, aus.structure_id
    FROM authorships a
    JOIN authorship_structures aus ON aus.authorship_id = a.id
    WITH DATA;

    CREATE UNIQUE INDEX authorship_structures_pkey
        ON authorship_structures (authorship_id, structure_id);
    CREATE INDEX idx_authorship_structures_structure_id
        ON authorship_structures (structure_id);
    CREATE UNIQUE INDEX publication_structures_pub_struct
        ON publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publication_structures (structure_id);
"""

_RESTORE_COLUMN = """
    ALTER TABLE source_authorships ADD COLUMN authorship_id integer;

    UPDATE source_authorships sa
    SET authorship_id = a.id
    FROM source_publications sp, authorships a
    WHERE sp.id = sa.source_publication_id
      AND a.publication_id = sp.publication_id
      AND a.person_id = sa.person_id;

    ALTER TABLE source_authorships
        ADD CONSTRAINT source_authorships_authorship_id_fkey
        FOREIGN KEY (authorship_id) REFERENCES authorships(id) ON DELETE SET NULL;
    CREATE INDEX idx_sa_authorship
        ON source_authorships (authorship_id) WHERE authorship_id IS NOT NULL;
"""


def upgrade() -> None:
    op.execute(_DROP_MATVIEWS)
    op.execute("ALTER TABLE source_authorships DROP COLUMN authorship_id")
    op.execute(_AUTHORSHIP_STRUCTURES)
    op.execute(_PUBLICATION_STRUCTURES_AND_INDEXES)


def downgrade() -> None:
    op.execute(_DROP_MATVIEWS)
    op.execute(_RESTORE_COLUMN)
    op.execute(_AUTHORSHIP_STRUCTURES_DOWNGRADE)
    op.execute(_PUBLICATION_STRUCTURES_AND_INDEXES)
