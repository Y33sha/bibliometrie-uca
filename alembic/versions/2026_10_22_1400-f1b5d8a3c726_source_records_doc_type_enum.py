"""Colonne doc_type de source_records typée par l'énumération doc_type

Revision ID: f1b5d8a3c726
Revises: c4d8e2f6a913
Create Date: 2026-10-22 14:00:00.000000

La conversion échoue si un enregistrement source porte un type hors de l'énumération. Le oneshot `interfaces/cli/oneshot/split_raw_doc_type_language.py` traduit ces types au préalable.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1b5d8a3c726"
down_revision: str | Sequence[str] | None = "c4d8e2f6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE invalid bigint;
        BEGIN
            SELECT count(*) INTO invalid FROM sources.source_records
            WHERE doc_type IS NOT NULL
              AND doc_type NOT IN (SELECT unnest(enum_range(NULL::public.doc_type))::text);
            IF invalid > 0 THEN
                RAISE EXCEPTION '% enregistrements sources ont un doc_type hors de l''énumération. Lancer d''abord python -m interfaces.cli.oneshot.split_raw_doc_type_language', invalid;
            END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE sources.source_records
            ALTER COLUMN doc_type TYPE public.doc_type USING doc_type::public.doc_type
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_records ALTER COLUMN doc_type TYPE text")
