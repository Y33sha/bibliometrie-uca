"""Les signatures d'une personne exclue ne rattachent pas leur publication à une structure

`authorship_structures` écarte les authorships d'une personne exclue (`persons.exclusion` non nul). `publication_structures`, qui en dépend, est recréée à l'identique. Les deux matviews sont recréées `WITH DATA`, puis le pipeline les rafraîchit `CONCURRENTLY`.

Revision ID: b6e2d9a4c731
Revises: f3a9c1e7d482
Create Date: 2026-10-02 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6e2d9a4c731"
down_revision: str | Sequence[str] | None = "f3a9c1e7d482"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DROP = """
    DROP MATERIALIZED VIEW publication_structures;
    DROP MATERIALIZED VIEW authorship_structures;
"""

_AUTHORSHIP_STRUCTURES = """
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

_AUTHORSHIP_STRUCTURES_DOWNGRADE = """
    CREATE MATERIALIZED VIEW authorship_structures AS
    SELECT DISTINCT sa.authorship_id, sas.structure_id
    FROM source_authorship_structures sas
    JOIN source_authorships sa ON sa.id = sas.source_authorship_id
    WHERE sa.authorship_id IS NOT NULL
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


def upgrade() -> None:
    op.execute(_DROP)
    op.execute(_AUTHORSHIP_STRUCTURES)
    op.execute(_PUBLICATION_STRUCTURES_AND_INDEXES)


def downgrade() -> None:
    op.execute(_DROP)
    op.execute(_AUTHORSHIP_STRUCTURES_DOWNGRADE)
    op.execute(_PUBLICATION_STRUCTURES_AND_INDEXES)
