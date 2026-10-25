"""Pays des adresses sans le moyen ror

Revision ID: 6a2f8d4b9c31
Revises: 8c3d5f7a1b26
Create Date: 2026-10-24 22:00:00.000000

Une adresse est partagée par toutes les signatures de même texte : le ROR d'une seule signature y devenait un pays pour toutes. Les candidats `ror` sont supprimés et leurs adresses mises en file pour la résolution de leur pays. L'énumération `country_detection_method` perd la valeur `ror`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6a2f8d4b9c31"
down_revision: str | Sequence[str] | None = "8c3d5f7a1b26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        WITH removed AS (
            DELETE FROM structures.address_country_candidates
            WHERE method = 'ror'
            RETURNING address_id
        )
        INSERT INTO queues.address_candidates_queue (id)
        SELECT DISTINCT address_id FROM removed
        ON CONFLICT (id) DO UPDATE SET seq = DEFAULT;

        ALTER TYPE public.country_detection_method RENAME TO country_detection_method_with_ror;
        CREATE TYPE public.country_detection_method AS ENUM (
            'manual', 'country_name', 'source_openalex', 'institution', 'city', 'source_scanr'
        );
        ALTER TABLE structures.address_country_candidates
            ALTER COLUMN method TYPE public.country_detection_method
            USING method::text::public.country_detection_method;
        DROP TYPE public.country_detection_method_with_ror;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TYPE public.country_detection_method RENAME TO country_detection_method_without_ror;
        CREATE TYPE public.country_detection_method AS ENUM (
            'manual', 'country_name', 'ror', 'source_openalex', 'institution', 'city', 'source_scanr'
        );
        ALTER TABLE structures.address_country_candidates
            ALTER COLUMN method TYPE public.country_detection_method
            USING method::text::public.country_detection_method;
        DROP TYPE public.country_detection_method_without_ror;
    """)
