"""ROR des signatures sources, journal des imports du dump ROR

`source_authorship_rors` associe chaque signature source aux ROR que la source lui attribue. `ror_id` est sans clé étrangère vers `ror_organizations` : une source peut citer un ROR absent du dump importé. `ror_dump_imports` garde une ligne par import du dump ROR.

Revision ID: c9f3b7e2d814
Revises: b4e8d1a63c27
Create Date: 2026-10-09 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9f3b7e2d814"
down_revision: str | Sequence[str] | None = "b4e8d1a63c27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE public.source_authorship_rors (
    source_authorship_id integer NOT NULL,
    ror_id text NOT NULL,
    CONSTRAINT source_authorship_rors_pkey PRIMARY KEY (source_authorship_id, ror_id),
    CONSTRAINT source_authorship_rors_source_authorship_id_fkey FOREIGN KEY (source_authorship_id)
        REFERENCES public.source_authorships(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.source_authorship_rors IS 'ROR attribués par la source à une signature. ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.';

CREATE INDEX ix_source_authorship_rors_ror_id ON public.source_authorship_rors (ror_id);

CREATE TABLE public.ror_dump_imports (
    version text NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ror_dump_imports_pkey PRIMARY KEY (version)
);

COMMENT ON TABLE public.ror_dump_imports IS 'Imports du dump ROR : nom de l''archive importée et date de l''import.';
""")


def downgrade() -> None:
    op.execute("""
DROP TABLE public.ror_dump_imports;
DROP TABLE public.source_authorship_rors;
""")
