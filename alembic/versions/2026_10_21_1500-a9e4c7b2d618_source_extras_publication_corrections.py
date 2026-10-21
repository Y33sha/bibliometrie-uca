"""Colonnes meta renommées source_extras ; colonne corrections de publications

Revision ID: a9e4c7b2d618
Revises: f3c8d2a6b517
Create Date: 2026-10-21 15:00:00.000000

`source_records.source_extras` reçoit les champs propres à une source, qu'aucune colonne commune ne reçoit. `publications.source_extras` est leur fusion par clé. `publications.corrections` garde, comme `source_records.corrections`, la valeur d'avant correction et la règle de chaque champ corrigé.

La trace des corrections d'une publication occupait la clé `corrections` de `publications.meta`. La migration retire cette clé et marque `keys_dirty` les enregistrements sources des publications concernées : la phase `publications` les recalcule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9e4c7b2d618"
down_revision: str | Sequence[str] | None = "f3c8d2a6b517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources.source_records RENAME COLUMN meta TO source_extras")
    op.execute("ALTER TABLE publications.publications RENAME COLUMN meta TO source_extras")
    op.execute(
        "ALTER INDEX publications.idx_publications_meta RENAME TO idx_publications_source_extras"
    )
    op.execute(
        "ALTER TABLE publications.publications"
        " ADD COLUMN corrections jsonb DEFAULT '{}'::jsonb NOT NULL,"
        " ADD CONSTRAINT publications_corrections_is_object"
        " CHECK (jsonb_typeof(corrections) = 'object')"
    )
    op.execute("""
        UPDATE sources.source_records sr SET keys_dirty = true
        FROM publications.publications p
        WHERE sr.publication_id = p.id AND p.source_extras ? 'corrections' AND NOT sr.keys_dirty
    """)
    op.execute("""
        UPDATE publications.publications SET source_extras = NULLIF(source_extras - 'corrections', '{}'::jsonb)
        WHERE source_extras ? 'corrections'
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE publications.publications DROP CONSTRAINT publications_corrections_is_object,"
        " DROP COLUMN corrections"
    )
    op.execute(
        "ALTER INDEX publications.idx_publications_source_extras RENAME TO idx_publications_meta"
    )
    op.execute("ALTER TABLE publications.publications RENAME COLUMN source_extras TO meta")
    op.execute("ALTER TABLE sources.source_records RENAME COLUMN source_extras TO meta")
