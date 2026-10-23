"""File d'attente du groupement des auteurs : publication_contributions_queue

Revision ID: b36ce1125278
Revises: c1298df84ca1
Create Date: 2026-10-23 16:00:00.000000

La file reçoit les publications marquées par `publications.contributions_dirty`, puis la colonne et son index partiel sont supprimés. `regroup_identifier_publications`, appelée par les déclencheurs des décisions sur un ORCID ou un IdRef et des corrections de prénom, marque les publications dans la file.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b36ce1125278"
down_revision: str | Sequence[str] | None = "c1298df84ca1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE queues.publication_contributions_queue (
            id integer PRIMARY KEY REFERENCES publications.publications (id) ON DELETE CASCADE,
            seq bigint GENERATED ALWAYS AS IDENTITY
        );
        INSERT INTO queues.publication_contributions_queue (id)
        SELECT id FROM publications.publications WHERE contributions_dirty;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.regroup_identifier_publications(id_type text, id_value text) RETURNS void
            LANGUAGE sql
            AS $$
                INSERT INTO queues.publication_contributions_queue (id)
                SELECT DISTINCT sr.publication_id
                FROM sources.source_records sr
                JOIN sources.source_contributions sc ON sc.source_record_id = sr.id
                JOIN sources.contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE sr.publication_id IS NOT NULL
                  AND ci.identifiers ? id_type
                  AND ci.identifiers ->> id_type = id_value
                ON CONFLICT (id) DO UPDATE SET seq = DEFAULT
            $$
    """)
    op.execute("""
        DROP INDEX publications.publications_contributions_dirty_idx;
        ALTER TABLE publications.publications DROP COLUMN contributions_dirty;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE publications.publications ADD COLUMN contributions_dirty boolean DEFAULT false NOT NULL;
        COMMENT ON COLUMN publications.publications.contributions_dirty IS
            'Groupes de contributions sources à recalculer : un enregistrement source a rejoint ou quitté la publication, ou ses contributions sources ont changé.';
        UPDATE publications.publications SET contributions_dirty = true
        WHERE id IN (SELECT id FROM queues.publication_contributions_queue);
        ALTER TABLE publications.publications ALTER COLUMN contributions_dirty SET DEFAULT true;
        CREATE INDEX publications_contributions_dirty_idx
            ON publications.publications USING btree (id) WHERE contributions_dirty;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.regroup_identifier_publications(id_type text, id_value text) RETURNS void
            LANGUAGE sql
            AS $$
                UPDATE publications.publications p SET contributions_dirty = true
                FROM sources.source_records sr
                JOIN sources.source_contributions sc ON sc.source_record_id = sr.id
                JOIN sources.contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE p.id = sr.publication_id AND NOT p.contributions_dirty
                  AND ci.identifiers ? id_type
                  AND ci.identifiers ->> id_type = id_value
            $$
    """)
    op.execute("DROP TABLE queues.publication_contributions_queue")
