"""Source inspire et identifiant CDS

La source `inspire` reçoit les fiches de la littérature d'INSPIRE-HEP. Le type d'identifiant `cds` reçoit le numéro de fiche du CERN Document Server, en chiffres.

Revision ID: b6d1e4a8c372
Revises: d4a7b2e9c5f1
Create Date: 2026-11-07 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6d1e4a8c372"
down_revision: str | Sequence[str] | None = "d4a7b2e9c5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'inspire' AFTER 'datacite'")
    op.execute("ALTER TYPE lookup_source ADD VALUE IF NOT EXISTS 'inspire' AFTER 'datacite'")
    op.execute("ALTER TYPE source_identifier_type ADD VALUE IF NOT EXISTS 'cds'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade supprime les identifiants CDS
    # et les enregistrements de la source, et laisse les valeurs dans les types, inutilisées.
    op.execute("""
        DELETE FROM sources.source_record_identifiers WHERE id_type::text = 'cds';
        DELETE FROM sources.source_records WHERE source::text = 'inspire';
        DELETE FROM sources.staging WHERE source::text = 'inspire';
    """)
