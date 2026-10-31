"""Plateformes hors des types de revue

Revision ID: a8d2c5f1e374
Revises: f2b8d4e6a913
Create Date: 2026-11-01 00:00:00.000000

Un entrepôt et un serveur de preprints sont des plateformes, jamais des revues : `serial_type` perd `repository` et `preprint_server`, `oa_model` perd `repository`. Les revues de ces types passent au type `unknown`, sans modèle open access, et leur saisie à la main de ces champs est retirée.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8d2c5f1e374"
down_revision: str | Sequence[str] | None = "f2b8d4e6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recreate_serial_type(values: str) -> str:
    return f"""
        ALTER TYPE public.serial_type RENAME TO serial_type_old;
        CREATE TYPE public.serial_type AS ENUM ({values});
        ALTER TABLE publishing.serials ALTER COLUMN serial_type DROP DEFAULT;
        ALTER TABLE publishing.serials
            ALTER COLUMN serial_type TYPE public.serial_type
            USING serial_type::text::public.serial_type;
        ALTER TABLE publishing.serials ALTER COLUMN serial_type SET DEFAULT 'unknown';
        DROP TYPE public.serial_type_old;
    """


def _recreate_oa_model(values: str) -> str:
    return f"""
        ALTER TYPE public.oa_model RENAME TO oa_model_old;
        CREATE TYPE public.oa_model AS ENUM ({values});
        ALTER TABLE publishing.serials
            ALTER COLUMN oa_model TYPE public.oa_model USING oa_model::text::public.oa_model;
        DROP TYPE public.oa_model_old;
    """


def upgrade() -> None:
    op.execute("""
        UPDATE publishing.serials
        SET serial_type = 'unknown', manual_fields = array_remove(manual_fields, 'serial_type')
        WHERE serial_type IN ('repository', 'preprint_server');

        UPDATE publishing.serials
        SET oa_model = NULL, manual_fields = array_remove(manual_fields, 'oa_model')
        WHERE oa_model = 'repository';
    """)
    op.execute(
        _recreate_serial_type(
            "'journal', 'data_journal', 'proceedings', 'book_series', 'media', 'unknown'"
        )
    )
    op.execute(_recreate_oa_model("'subscription', 'full_oa', 'diamond'"))


def downgrade() -> None:
    op.execute(_recreate_oa_model("'subscription', 'full_oa', 'diamond', 'repository'"))
    op.execute(
        _recreate_serial_type(
            "'journal', 'data_journal', 'proceedings', 'repository', 'book_series',"
            " 'preprint_server', 'media', 'unknown'"
        )
    )
