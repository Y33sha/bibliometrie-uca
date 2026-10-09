"""Référentiel ROR : organisations et relations parent/enfant

Les tables `ror_organizations` et `ror_relations` reçoivent le dump du Research Organization Registry. `structures.ror_id` relie le référentiel interne à ce référentiel externe.

Revision ID: a7c2e5f91b3d
Revises: f3c9a1d7e2b4
Create Date: 2026-10-09 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c2e5f91b3d"
down_revision: str | Sequence[str] | None = "f3c9a1d7e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TYPE public.ror_status AS ENUM ('active', 'inactive', 'withdrawn');

CREATE TYPE public.ror_type AS ENUM (
    'archive', 'company', 'education', 'facility', 'funder', 'government', 'healthcare',
    'nonprofit', 'other'
);

CREATE TABLE public.ror_organizations (
    ror_id text NOT NULL,
    name text NOT NULL,
    country_code character(2) NOT NULL,
    types public.ror_type[] NOT NULL,
    status public.ror_status NOT NULL,
    CONSTRAINT ror_organizations_pkey PRIMARY KEY (ror_id)
);

COMMENT ON TABLE public.ror_organizations IS 'Organisations du Research Organization Registry, chargées depuis son dump. Référentiel externe en lecture seule : structures.ror_id le relie au référentiel interne.';

CREATE TABLE public.ror_relations (
    parent_ror_id text NOT NULL,
    child_ror_id text NOT NULL,
    CONSTRAINT ror_relations_pkey PRIMARY KEY (parent_ror_id, child_ror_id),
    CONSTRAINT ror_relations_no_self_reference CHECK (parent_ror_id <> child_ror_id),
    CONSTRAINT ror_relations_parent_ror_id_fkey FOREIGN KEY (parent_ror_id)
        REFERENCES public.ror_organizations(ror_id) ON DELETE CASCADE,
    CONSTRAINT ror_relations_child_ror_id_fkey FOREIGN KEY (child_ror_id)
        REFERENCES public.ror_organizations(ror_id) ON DELETE CASCADE
);

COMMENT ON TABLE public.ror_relations IS 'Relations parent/enfant entre organisations du Research Organization Registry.';

CREATE INDEX ix_ror_relations_child_ror_id ON public.ror_relations (child_ror_id);
""")


def downgrade() -> None:
    op.execute("""
DROP TABLE public.ror_relations;
DROP TABLE public.ror_organizations;
DROP TYPE public.ror_type;
DROP TYPE public.ror_status;
""")
