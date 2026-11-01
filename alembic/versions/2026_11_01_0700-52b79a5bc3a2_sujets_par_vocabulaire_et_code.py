"""Sujets identifiés par leur vocabulaire et leur code, liés aux enregistrements sources

Revision ID: 52b79a5bc3a2
Revises: 19301d8c9878
Create Date: 2026-11-01 07:00:00.000000

Un sujet est identifié par son vocabulaire et son code. Il a un niveau et un parent. La normalisation lie chaque enregistrement source aux sujets donnés par la source (`sources.source_record_subjects`). La phase `subjects` en dérive `publication_subjects`, ancêtres compris.

Les sujets et leurs liens aux publications sont vidés : aucun lien n'est rejeté. Les scripts ponctuels du stock remplissent `source_record_subjects`, puis le run suivant dérive les liens de toutes les publications.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "52b79a5bc3a2"
down_revision: str | Sequence[str] | None = "19301d8c9878"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.subject_vocabulary AS ENUM (
            'openalex', 'hal_domain', 'rameau', 'theses_discipline'
        )
    """)
    op.execute("TRUNCATE publications.publication_subjects, publications.subjects")
    op.execute("DROP INDEX publications.subjects_label_key")
    op.execute("""
        ALTER TABLE publications.subjects
            DROP COLUMN language,
            ADD COLUMN vocabulary public.subject_vocabulary NOT NULL,
            ADD COLUMN code text NOT NULL,
            ADD COLUMN level smallint NOT NULL,
            ADD COLUMN parent_id integer REFERENCES publications.subjects (id),
            ADD CONSTRAINT subjects_vocabulary_code_key UNIQUE (vocabulary, code)
    """)
    op.execute("CREATE INDEX subjects_parent_idx ON publications.subjects (parent_id)")
    op.execute("""
        COMMENT ON COLUMN publications.subjects.code IS
        'Code du sujet dans son vocabulaire : identifiant OpenAlex sans préfixe d''URL, code de domaine HAL, PPN RAMEAU, libellé normalisé d''une discipline de thèse.'
    """)
    op.execute("""
        COMMENT ON COLUMN publications.subjects.level IS
        'Profondeur dans le vocabulaire : 1 pour une racine.'
    """)
    op.execute("""
        COMMENT ON COLUMN publications.subjects.parent_id IS
        'Sujet du niveau supérieur, du même vocabulaire.'
    """)
    op.execute("""
        CREATE TABLE sources.source_record_subjects (
            source_record_id integer NOT NULL
                REFERENCES sources.source_records (id) ON DELETE CASCADE,
            subject_id integer NOT NULL REFERENCES publications.subjects (id),
            score real,
            PRIMARY KEY (source_record_id, subject_id)
        )
    """)
    op.execute(
        "CREATE INDEX source_record_subjects_subject_idx"
        " ON sources.source_record_subjects (subject_id)"
    )
    op.execute("""
        COMMENT ON TABLE sources.source_record_subjects IS
        'Sujets donnés par un enregistrement source. Leurs ancêtres découlent de subjects.parent_id.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.source_record_subjects.score IS
        'Score OpenAlex du topic. Nul pour les autres sources.'
    """)
    op.execute(
        "UPDATE publications.publications SET subjects_ingested_at = NULL"
        " WHERE subjects_ingested_at IS NOT NULL"
    )
    op.execute("REFRESH MATERIALIZED VIEW publications.subject_cooccurrences")


def downgrade() -> None:
    op.execute("DROP TABLE sources.source_record_subjects")
    op.execute("TRUNCATE publications.publication_subjects, publications.subjects")
    op.execute("""
        ALTER TABLE publications.subjects
            DROP CONSTRAINT subjects_vocabulary_code_key,
            DROP COLUMN parent_id,
            DROP COLUMN level,
            DROP COLUMN code,
            DROP COLUMN vocabulary,
            ADD COLUMN language text
    """)
    op.execute("CREATE UNIQUE INDEX subjects_label_key ON publications.subjects (lower(label))")
    op.execute("DROP TYPE public.subject_vocabulary")
    op.execute(
        "UPDATE publications.publications SET subjects_ingested_at = NULL"
        " WHERE subjects_ingested_at IS NOT NULL"
    )
    op.execute("REFRESH MATERIALIZED VIEW publications.subject_cooccurrences")
