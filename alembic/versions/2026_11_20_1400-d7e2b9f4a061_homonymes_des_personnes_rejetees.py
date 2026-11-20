"""Homonymes des personnes rejetées

La colonne `persons.homonym_of` relie l'homonyme d'une personne à cette personne. Le type `resolution_mode` gagne la valeur `homonym` : contribution d'une publication rejetée pour une personne, rattachée à l'homonyme de cette personne.

Revision ID: d7e2b9f4a061
Revises: c5d8a1e3f276
Create Date: 2026-11-20 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7e2b9f4a061"
down_revision: str | Sequence[str] | None = "c5d8a1e3f276"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXCLUSION_COMMENT = (
    "Motif d'exclusion : not_a_person (fausse entité), "
    "out_of_perimeter (personne réelle hors du périmètre, ou homonyme d'une personne rejetée). "
    "Nul pour une personne retenue."
)
_PREVIOUS_EXCLUSION_COMMENT = (
    "Motif d'exclusion décidé à la main : not_a_person (fausse entité), "
    "out_of_perimeter (personne réelle rattachée au périmètre par erreur). "
    "Nul pour une personne retenue."
)
_HOMONYM_COMMENT = (
    "Personne dont celle-ci est l'homonyme, créé pour les publications rejetées pour elle."
)


def upgrade() -> None:
    op.execute("ALTER TYPE resolution_mode ADD VALUE IF NOT EXISTS 'homonym'")
    op.execute("""
        ALTER TABLE persons.persons
        ADD COLUMN homonym_of integer REFERENCES persons.persons(id) ON DELETE SET NULL
    """)
    op.execute("CREATE INDEX persons_homonym_of_idx ON persons.persons (homonym_of)")
    op.execute(
        f"COMMENT ON COLUMN persons.persons.homonym_of IS '{_HOMONYM_COMMENT.replace("'", "''")}'"
    )
    op.execute(
        f"COMMENT ON COLUMN persons.persons.exclusion IS '{_EXCLUSION_COMMENT.replace("'", "''")}'"
    )


def downgrade() -> None:
    # PostgreSQL ne retire pas une valeur d'enum : les contributions rattachées à un homonyme perdent leur personne, puis les homonymes sont supprimés.
    op.execute("""
        UPDATE publications.contributions SET person_id = NULL, resolution_mode = NULL
        WHERE resolution_mode::text = 'homonym'
           OR person_id IN (SELECT id FROM persons.persons WHERE homonym_of IS NOT NULL)
    """)
    op.execute("DELETE FROM persons.persons WHERE homonym_of IS NOT NULL")
    op.execute("ALTER TABLE persons.persons DROP COLUMN homonym_of")
    op.execute(
        f"COMMENT ON COLUMN persons.persons.exclusion IS '{_PREVIOUS_EXCLUSION_COMMENT.replace("'", "''")}'"
    )
