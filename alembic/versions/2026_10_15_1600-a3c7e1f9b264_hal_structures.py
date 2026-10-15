"""Référentiel des structures HAL, et structures HAL des signatures

- `ref.hal_structures` : structures du référentiel HAL (`ref/structure`), avec leur statut et leurs dates de validité.
- `ref.hal_structure_relations` : couples (parent, enfant), d'après `parentDocid_i`.
- `ref.hal_structure_aliases` : fiches en double fondues dans une structure conservée, d'après `aliasDocid_i`.
- `sources.source_authorship_hal_structures` : structures HAL directes d'une signature, sans clé étrangère vers le référentiel, qui se remplit après la normalisation.
- Le type `perimeter_evidence` gagne les valeurs `hal_structure` et `ror`.

Revision ID: a3c7e1f9b264
Revises: f4b8d2a6c917
Create Date: 2026-10-15 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3c7e1f9b264"
down_revision: str | Sequence[str] | None = "f4b8d2a6c917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TYPE public.perimeter_evidence ADD VALUE 'hal_structure';
        ALTER TYPE public.perimeter_evidence ADD VALUE 'ror';

        CREATE TYPE public.hal_structure_status AS ENUM ('VALID', 'OLD', 'INCOMING');

        CREATE TABLE ref.hal_structures (
            hal_structure_id integer PRIMARY KEY,
            name text NOT NULL,
            acronym text,
            structure_type text NOT NULL,
            country_code char(2),
            status public.hal_structure_status NOT NULL,
            ror_id text,
            start_date date,
            end_date date,
            fetched_at timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE ref.hal_structures IS
            'Structures du référentiel HAL (ref/structure). Référentiel externe : son ROR, ou structures.api_ids->''hal'', le relie au référentiel interne.';
        CREATE INDEX ix_hal_structures_ror_id ON ref.hal_structures (ror_id);

        CREATE TABLE ref.hal_structure_relations (
            parent_id integer NOT NULL REFERENCES ref.hal_structures ON DELETE CASCADE,
            child_id integer NOT NULL REFERENCES ref.hal_structures ON DELETE CASCADE,
            CONSTRAINT hal_structure_relations_pkey PRIMARY KEY (parent_id, child_id),
            CONSTRAINT hal_structure_relations_no_self_reference CHECK (parent_id <> child_id)
        );
        COMMENT ON TABLE ref.hal_structure_relations IS 'Relations parent/enfant entre structures du référentiel HAL.';
        CREATE INDEX ix_hal_structure_relations_child_id ON ref.hal_structure_relations (child_id);

        CREATE TABLE ref.hal_structure_aliases (
            alias_id integer PRIMARY KEY,
            hal_structure_id integer NOT NULL REFERENCES ref.hal_structures ON DELETE CASCADE
        );
        COMMENT ON TABLE ref.hal_structure_aliases IS
            'Fiches en double du référentiel HAL, fondues dans une structure conservée.';
        CREATE INDEX ix_hal_structure_aliases_hal_structure_id ON ref.hal_structure_aliases (hal_structure_id);

        CREATE TABLE sources.source_authorship_hal_structures (
            source_authorship_id integer NOT NULL REFERENCES sources.source_authorships ON DELETE CASCADE,
            hal_structure_id integer NOT NULL,
            CONSTRAINT source_authorship_hal_structures_pkey PRIMARY KEY (source_authorship_id, hal_structure_id)
        );
        CREATE INDEX ix_source_authorship_hal_structures_hal_structure_id
            ON sources.source_authorship_hal_structures (hal_structure_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE sources.source_authorship_hal_structures;
        DROP TABLE ref.hal_structure_aliases;
        DROP TABLE ref.hal_structure_relations;
        DROP TABLE ref.hal_structures;
        DROP TYPE public.hal_structure_status;
    """)
    # PostgreSQL ne retire pas une valeur d'enum : `hal_structure` et `ror` restent dans `perimeter_evidence`.
