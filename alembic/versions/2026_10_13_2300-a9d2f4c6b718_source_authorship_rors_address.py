"""ROR d'une signature rattaché à l'adresse de son affiliation

`source_authorship_rors.address_id` désigne l'adresse dont l'affiliation porte le ROR. Il est vide pour un ROR que la source donne sans texte d'affiliation : le ROR reste alors rattaché à la seule signature. La clé primaire `(source_authorship_id, ror_id)` devient une contrainte d'unicité sur `(source_authorship_id, ror_id, address_id)`, deux adresses vides étant égales.

Les lignes existantes gardent une adresse vide jusqu'à la renormalisation de leur notice.

Revision ID: a9d2f4c6b718
Revises: f1c5a9d3e740
Create Date: 2026-10-13 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9d2f4c6b718"
down_revision: str | Sequence[str] | None = "f1c5a9d3e740"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_authorship_rors
            ADD COLUMN address_id integer REFERENCES structures.addresses(id) ON DELETE CASCADE;
        ALTER TABLE sources.source_authorship_rors DROP CONSTRAINT source_authorship_rors_pkey;
        ALTER TABLE sources.source_authorship_rors
            ADD CONSTRAINT source_authorship_rors_key
            UNIQUE NULLS NOT DISTINCT (source_authorship_id, ror_id, address_id);
        CREATE INDEX ix_source_authorship_rors_address_id
            ON sources.source_authorship_rors (address_id);
        COMMENT ON TABLE sources.source_authorship_rors IS
            'ROR attribués par la source à une signature, rattachés à l''adresse de leur affiliation, ou à la seule signature quand l''affiliation est sans texte (address_id vide). ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.';
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM sources.source_authorship_rors r
        USING sources.source_authorship_rors other
        WHERE r.source_authorship_id = other.source_authorship_id
          AND r.ror_id = other.ror_id
          AND r.ctid > other.ctid;
        DROP INDEX sources.ix_source_authorship_rors_address_id;
        ALTER TABLE sources.source_authorship_rors DROP CONSTRAINT source_authorship_rors_key;
        ALTER TABLE sources.source_authorship_rors DROP COLUMN address_id;
        ALTER TABLE sources.source_authorship_rors
            ADD CONSTRAINT source_authorship_rors_pkey PRIMARY KEY (source_authorship_id, ror_id);
        COMMENT ON TABLE sources.source_authorship_rors IS
            'ROR attribués par la source à une signature. ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.';
    """)
