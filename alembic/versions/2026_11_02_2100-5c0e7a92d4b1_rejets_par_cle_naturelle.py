"""Rejets ancrés sur la clé naturelle de l'enregistrement source

Le rejet d'un couple (enregistrement source, personne) vise (source, source_id), sans clé étrangère vers `source_records`. Il survit à la disparition de l'enregistrement source, et s'applique à son retour.

Revision ID: 5c0e7a92d4b1
Revises: 1b8fc52a4010
Create Date: 2026-11-02 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5c0e7a92d4b1"
down_revision: str | Sequence[str] | None = "1b8fc52a4010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
ALTER TABLE persons.rejected_contributions
    ADD COLUMN source public.source_type,
    ADD COLUMN source_id text;

UPDATE persons.rejected_contributions r
SET source = sr.source, source_id = sr.source_id
FROM sources.source_records sr
WHERE sr.id = r.source_record_id;

ALTER TABLE persons.rejected_contributions
    DROP CONSTRAINT rejected_contributions_pkey,
    DROP CONSTRAINT rejected_contributions_source_record_id_fkey,
    DROP COLUMN source_record_id,
    ALTER COLUMN source SET NOT NULL,
    ALTER COLUMN source_id SET NOT NULL,
    ADD CONSTRAINT rejected_contributions_pkey PRIMARY KEY (source, source_id, person_id);

COMMENT ON TABLE persons.rejected_contributions IS 'Couples (enregistrement source, personne) rejetés par l''administration, par clé naturelle de l''enregistrement source. Le rejet d''un enregistrement source disparu de sa source s''applique à son retour.';
"""

# Un rejet dont l'enregistrement source est absent de la base est perdu.
_DOWNGRADE = """
COMMENT ON TABLE persons.rejected_contributions IS NULL;

ALTER TABLE persons.rejected_contributions ADD COLUMN source_record_id integer;

UPDATE persons.rejected_contributions r
SET source_record_id = sr.id
FROM sources.source_records sr
WHERE sr.source = r.source AND sr.source_id = r.source_id;

DELETE FROM persons.rejected_contributions WHERE source_record_id IS NULL;

ALTER TABLE persons.rejected_contributions
    DROP CONSTRAINT rejected_contributions_pkey,
    DROP COLUMN source,
    DROP COLUMN source_id,
    ALTER COLUMN source_record_id SET NOT NULL,
    ADD CONSTRAINT rejected_contributions_pkey PRIMARY KEY (source_record_id, person_id),
    ADD CONSTRAINT rejected_contributions_source_record_id_fkey
        FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
