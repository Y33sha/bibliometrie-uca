"""Groupes de signatures : `source_authorship_groups` et `grouped_source_authorships`

Un groupe réunit les signatures d'un même auteur dans une publication, avec au maximum une signature par notice. Une personne correspond au maximum à un groupe par publication.

Revision ID: 7d2f9b4e1a63
Revises: 9c4e2a7f1b63
Create Date: 2026-10-18 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7d2f9b4e1a63"
down_revision: str | Sequence[str] | None = "9c4e2a7f1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE public.grouping_method AS ENUM ('reference', 'name', 'identifier', 'order', 'model')"
    )
    op.execute("""
        CREATE TABLE publications.source_authorship_groups (
            id serial PRIMARY KEY,
            publication_id integer NOT NULL
                REFERENCES publications.publications(id) ON DELETE CASCADE,
            person_id integer REFERENCES persons.persons(id) ON DELETE SET NULL,
            resolution_mode public.resolution_mode,
            reference_position smallint,
            CONSTRAINT source_authorship_groups_publication_person_uq UNIQUE (publication_id, person_id)
        )
    """)
    op.execute(
        "CREATE INDEX source_authorship_groups_person_id_idx"
        " ON publications.source_authorship_groups (person_id)"
    )
    op.execute("""
        COMMENT ON TABLE publications.source_authorship_groups IS
            'Signatures d''un même auteur dans une publication, avec au maximum une signature par notice. reference_position : position dans la liste la plus longue. Une personne correspond au maximum à un groupe par publication.'
    """)
    op.execute("""
        CREATE TABLE publications.grouped_source_authorships (
            source_authorship_id integer PRIMARY KEY
                REFERENCES sources.source_authorships(id) ON DELETE CASCADE,
            group_id integer NOT NULL
                REFERENCES publications.source_authorship_groups(id) ON DELETE CASCADE,
            source_publication_id integer NOT NULL
                REFERENCES sources.source_publications(id) ON DELETE CASCADE,
            method public.grouping_method NOT NULL,
            score real,
            margin real,
            CONSTRAINT grouped_source_authorships_group_notice_uq UNIQUE (group_id, source_publication_id),
            CONSTRAINT grouped_source_authorships_score_check
                CHECK (method = 'model' OR (score IS NULL AND margin IS NULL))
        )
    """)
    op.execute("""
        COMMENT ON TABLE publications.grouped_source_authorships IS
            'Appartenance d''une signature à son groupe. method : origine du lien. score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart à la meilleure autre possibilité de l''affectation.'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE publications.grouped_source_authorships")
    op.execute("DROP TABLE publications.source_authorship_groups")
    op.execute("DROP TYPE public.grouping_method")
