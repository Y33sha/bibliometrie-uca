"""Un rejet vise les notices d'une publication

`rejected_authorships` passe de (publication, personne) à (notice, personne). Les notices sont stables d'une réconciliation à l'autre, les publications non : une fusion ou une scission perdait les rejets. Chaque rejet existant est repris sur toutes les notices actuelles de sa publication, avec sa date.

Revision ID: b6e2f9a4c358
Revises: a5d1e8f3b249
Create Date: 2026-10-11 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6e2f9a4c358"
down_revision: str | Sequence[str] | None = "a5d1e8f3b249"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE rejected_authorships_by_notice (
            source_publication_id integer NOT NULL
                REFERENCES source_publications(id) ON DELETE CASCADE,
            person_id integer NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            PRIMARY KEY (source_publication_id, person_id)
        );
        INSERT INTO rejected_authorships_by_notice (source_publication_id, person_id, created_at)
        SELECT sp.id, r.person_id, r.created_at
        FROM rejected_authorships r
        JOIN source_publications sp ON sp.publication_id = r.publication_id;
        DROP TABLE rejected_authorships;
        ALTER TABLE rejected_authorships_by_notice RENAME TO rejected_authorships;
        ALTER INDEX rejected_authorships_by_notice_pkey RENAME TO rejected_authorships_pkey;
        ALTER TABLE rejected_authorships
            RENAME CONSTRAINT rejected_authorships_by_notice_source_publication_id_fkey
            TO rejected_authorships_source_publication_id_fkey;
        ALTER TABLE rejected_authorships
            RENAME CONSTRAINT rejected_authorships_by_notice_person_id_fkey
            TO rejected_authorships_person_id_fkey;
        CREATE INDEX idx_rejected_authorships_person ON rejected_authorships (person_id);
    """)


def downgrade() -> None:
    op.execute("""
        CREATE TABLE rejected_authorships_by_publication (
            publication_id integer NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
            person_id integer NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            PRIMARY KEY (publication_id, person_id)
        );
        INSERT INTO rejected_authorships_by_publication (publication_id, person_id, created_at)
        SELECT sp.publication_id, r.person_id, min(r.created_at)
        FROM rejected_authorships r
        JOIN source_publications sp ON sp.id = r.source_publication_id
        WHERE sp.publication_id IS NOT NULL
        GROUP BY sp.publication_id, r.person_id;
        DROP TABLE rejected_authorships;
        ALTER TABLE rejected_authorships_by_publication RENAME TO rejected_authorships;
        ALTER INDEX rejected_authorships_by_publication_pkey RENAME TO rejected_authorships_pkey;
        ALTER TABLE rejected_authorships
            RENAME CONSTRAINT rejected_authorships_by_publication_publication_id_fkey
            TO rejected_authorships_publication_id_fkey;
        ALTER TABLE rejected_authorships
            RENAME CONSTRAINT rejected_authorships_by_publication_person_id_fkey
            TO rejected_authorships_person_id_fkey;
    """)
