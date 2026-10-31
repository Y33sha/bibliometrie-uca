"""Table des embargos

Un embargo vise un enregistrement source : la date de fin d'embargo du fichier déposé dans HAL, ou un embargo sans date déclaré par theses.fr. La date des copies HAL et les thèses de statut `embargoed` passent dans `sources.embargoes`. La colonne `embargo_until` des localisations est supprimée.

Revision ID: 5d2f8b3c9e61
Revises: 7c3e9a5b1d42
Create Date: 2026-10-31 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d2f8b3c9e61"
down_revision: str | Sequence[str] | None = "7c3e9a5b1d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sources.embargoes (
            source_record_id integer PRIMARY KEY
                REFERENCES sources.source_records (id) ON DELETE CASCADE,
            until date
        )
    """)
    op.execute("""
        COMMENT ON TABLE sources.embargoes IS
        'Embargo déclaré par un enregistrement source : fichier déposé dans HAL, thèse de theses.fr.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.embargoes.until IS
        'Date de fin d''embargo. Nulle quand la source déclare un embargo sans date.'
    """)
    op.execute("""
        INSERT INTO sources.embargoes (source_record_id, until)
        SELECT source_record_id, max(embargo_until)
        FROM sources.source_record_locations
        WHERE embargo_until IS NOT NULL
        GROUP BY source_record_id
    """)
    op.execute("""
        INSERT INTO sources.embargoes (source_record_id, until)
        SELECT id, NULL FROM sources.source_records
        WHERE source = 'theses' AND oa_status = 'embargoed'
        ON CONFLICT (source_record_id) DO NOTHING
    """)
    op.execute("ALTER TABLE sources.source_record_locations DROP COLUMN embargo_until")


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_record_locations ADD COLUMN embargo_until date")
    op.execute("""
        COMMENT ON COLUMN sources.source_record_locations.embargo_until IS
        'Date de fin d''embargo. La copie est fermée jusqu''à cette date.'
    """)
    op.execute("""
        UPDATE sources.source_record_locations l SET embargo_until = e.until
        FROM sources.embargoes e
        WHERE e.source_record_id = l.source_record_id AND e.until IS NOT NULL
          AND l.pdf_url IS NOT NULL
    """)
    op.execute("DROP TABLE sources.embargoes")
