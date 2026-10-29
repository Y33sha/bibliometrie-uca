"""Suppression de la colonne source_records.doi

Revision ID: b6d1f9a3c8e2
Revises: e2b8f4c6a913
Create Date: 2026-10-29 18:00:00.000000

Les DOI d'un enregistrement source sont dans `source_record_identifiers`, avec leur rôle et leur statut. L'entrée `doi` de `corrections` part avec la colonne.

Le retour arrière recrée la colonne avec le premier DOI actif de rôle autre que `related`, par rôle puis par valeur.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6d1f9a3c8e2"
down_revision: str | Sequence[str] | None = "e2b8f4c6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE sources.source_records SET corrections = corrections - 'doi'
        WHERE corrections ? 'doi'
    """)
    op.execute("ALTER TABLE sources.source_records DROP COLUMN doi")


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_records ADD COLUMN doi text")
    op.execute("""
        UPDATE sources.source_records sr SET doi = d.id_value
        FROM (
            SELECT DISTINCT ON (source_record_id) source_record_id, id_value
            FROM sources.source_record_identifiers
            WHERE id_type = 'doi' AND role <> 'related' AND removed_by IS NULL
            ORDER BY source_record_id,
                     CASE role WHEN 'primary' THEN 1 WHEN 'derived' THEN 2 ELSE 3 END,
                     id_value COLLATE "C"
        ) d
        WHERE d.source_record_id = sr.id
    """)
    op.execute(
        "CREATE INDEX idx_source_records_doi ON sources.source_records (doi) WHERE doi IS NOT NULL"
    )
