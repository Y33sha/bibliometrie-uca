"""Identifiants des enregistrements sources

Revision ID: a1d103de75ef
Revises: c4e8a1f7d236
Create Date: 2026-10-28 18:00:00.000000

`source_record_identifiers` relie un enregistrement source à ses identifiants, chacun avec son rôle et la règle de correction qui le retire.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1d103de75ef"
down_revision: str | Sequence[str] | None = "c4e8a1f7d236"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.source_identifier_type AS ENUM
            ('doi', 'hal_id', 'nnt', 'pmid', 'pmcid', 'arxiv_id', 'isbn', 'eisbn');
        CREATE TYPE public.source_identifier_role AS ENUM
            ('primary', 'derived', 'secondary', 'related');

        CREATE TABLE sources.source_record_identifiers (
            source_record_id integer NOT NULL
                REFERENCES sources.source_records(id) ON DELETE CASCADE,
            id_type public.source_identifier_type NOT NULL,
            id_value text NOT NULL,
            role public.source_identifier_role NOT NULL,
            removed_by text,
            PRIMARY KEY (source_record_id, id_type, id_value)
        );
        CREATE INDEX idx_source_record_identifiers_value
            ON sources.source_record_identifiers (id_type, id_value);
        CREATE UNIQUE INDEX uq_source_record_identifiers_derived
            ON sources.source_record_identifiers (source_record_id) WHERE role = 'derived';
        COMMENT ON TABLE sources.source_record_identifiers IS
            'Identifiants d''un enregistrement source, réécrits à chaque normalisation.';
        COMMENT ON COLUMN sources.source_record_identifiers.id_value IS
            'Forme normalisée de l''identifiant.';
        COMMENT ON COLUMN sources.source_record_identifiers.role IS
            'primary : identifiant de l''enregistrement dans la source. derived : identifiant de l''enregistrement d''une autre source dont la source tire le sien. secondary : identifiant que la source attribue au même document. related : identifiant d''un document lié.';
        COMMENT ON COLUMN sources.source_record_identifiers.removed_by IS
            'Règle de correction qui retire l''identifiant. NULL : identifiant actif.';
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE sources.source_record_identifiers;
        DROP TYPE public.source_identifier_role;
        DROP TYPE public.source_identifier_type;
    """)
