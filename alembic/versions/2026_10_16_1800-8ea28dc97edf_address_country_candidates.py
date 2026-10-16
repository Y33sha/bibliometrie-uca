"""Pays candidats des adresses

`address_country_candidates` garde chaque pays qu'un moyen de détection propose pour une adresse. `addresses.countries` en dérive par la préséance du domaine (`retained_countries`). `addresses.candidates_dirty` marque une adresse à traiter : détection par le texte, puis résolution. Une adresse est marquée à sa création et à chaque candidat ajouté ; toutes les adresses existantes le sont, pour un premier traitement complet.

Revision ID: 8ea28dc97edf
Revises: 3458e6b6593b
Create Date: 2026-10-16 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8ea28dc97edf"
down_revision: str | Sequence[str] | None = "3458e6b6593b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.country_detection_method AS ENUM (
            'manual', 'country_name', 'ror', 'source_openalex', 'institution', 'city', 'source_scanr'
        );

        CREATE TABLE structures.address_country_candidates (
            address_id integer NOT NULL REFERENCES structures.addresses (id) ON DELETE CASCADE,
            country_code character(2) NOT NULL REFERENCES ref.countries (code),
            method public.country_detection_method NOT NULL,
            detected_at timestamp with time zone NOT NULL DEFAULT now(),
            PRIMARY KEY (address_id, country_code, method)
        );
        COMMENT ON TABLE structures.address_country_candidates IS
            'Pays proposé pour une adresse par un moyen de détection. addresses.countries en dérive par la préséance du domaine.';

        ALTER TABLE structures.addresses ADD COLUMN candidates_dirty boolean NOT NULL DEFAULT true;
        COMMENT ON COLUMN structures.addresses.candidates_dirty IS
            'Adresse à traiter : détection du pays par le texte, puis résolution des candidats.';
        CREATE INDEX idx_addresses_candidates_dirty ON structures.addresses (id) WHERE candidates_dirty;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX structures.idx_addresses_candidates_dirty;
        ALTER TABLE structures.addresses DROP COLUMN candidates_dirty;
        DROP TABLE structures.address_country_candidates;
        DROP TYPE public.country_detection_method;
    """)
