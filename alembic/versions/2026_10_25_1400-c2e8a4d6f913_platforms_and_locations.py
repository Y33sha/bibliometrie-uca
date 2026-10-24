"""Plateformes et localisations des enregistrements sources

Revision ID: c2e8a4d6f913
Revises: a7c3e9f1b524
Create Date: 2026-10-25 14:00:00.000000

`platforms` réunit les lieux qui hébergent des publications : entrepôts, serveurs de preprints, plateformes d'éditeurs. `source_record_locations` donne les localisations d'un enregistrement source, telles que sa source les décrit.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2e8a4d6f913"
down_revision: str | Sequence[str] | None = "a7c3e9f1b524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.platform_type AS ENUM
            ('repository', 'preprint_server', 'publisher_platform', 'unknown');

        CREATE TABLE publishing.platforms (
            id serial PRIMARY KEY,
            name text NOT NULL,
            name_normalized text NOT NULL,
            platform_type public.platform_type NOT NULL DEFAULT 'unknown',
            openalex_id text UNIQUE,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE publishing.platforms IS
            'Lieux qui hébergent des publications : entrepôts, serveurs de preprints, plateformes d''éditeurs.';
        COMMENT ON COLUMN publishing.platforms.openalex_id IS
            'Source OpenAlex de la plateforme, dont elle prend le nom.';

        CREATE TABLE sources.source_record_locations (
            source_record_id integer NOT NULL
                REFERENCES sources.source_records(id) ON DELETE CASCADE,
            url text NOT NULL,
            pdf_url text,
            oai_id text,
            version text,
            license public.license_type,
            is_oa boolean,
            platform_id integer REFERENCES publishing.platforms(id),
            PRIMARY KEY (source_record_id, url)
        );
        CREATE INDEX idx_source_record_locations_platform ON sources.source_record_locations (platform_id)
            WHERE platform_id IS NOT NULL;
        COMMENT ON TABLE sources.source_record_locations IS
            'Localisations d''un enregistrement source, réécrites à chaque normalisation.';
        COMMENT ON COLUMN sources.source_record_locations.oai_id IS
            'Identifiant OAI-PMH de la copie, que déclare l''entrepôt.';
        COMMENT ON COLUMN sources.source_record_locations.version IS
            'Version de la copie dans le vocabulaire de la source (submittedVersion, acceptedVersion, publishedVersion).';
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE sources.source_record_locations;
        DROP TABLE publishing.platforms;
        DROP TYPE public.platform_type;
    """)
