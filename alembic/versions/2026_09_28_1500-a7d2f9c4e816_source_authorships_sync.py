"""source_authorships : position différable, empreinte des champs écrits

La normalisation d'une notice rapproche ses signatures entrantes de celles en base et les met à jour en une instruction. Une permutation de positions heurte la contrainte `(source_publication_id, author_position)` quand elle est vérifiée ligne à ligne : la contrainte devient `DEFERRABLE INITIALLY IMMEDIATE`, vérifiée en fin d'instruction. `content_hash` porte l'empreinte des champs écrits, pour laisser en l'état une signature inchangée.

Revision ID: a7d2f9c4e816
Revises: f1c8b3d6a472
Create Date: 2026-09-28 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d2f9c4e816"
down_revision: str | Sequence[str] | None = "f1c8b3d6a472"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "source_authorships_pub_pos_key"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "source_authorships", type_="unique")
    op.create_unique_constraint(
        _CONSTRAINT,
        "source_authorships",
        ["source_publication_id", "author_position"],
        deferrable=True,
        initially="IMMEDIATE",
    )
    op.add_column(
        "source_authorships",
        sa.Column(
            "content_hash",
            sa.Text(),
            nullable=True,
            comment="Empreinte des champs écrits par la normalisation, adresses comprises.",
        ),
    )


def downgrade() -> None:
    op.drop_column("source_authorships", "content_hash")
    op.drop_constraint(_CONSTRAINT, "source_authorships", type_="unique")
    op.create_unique_constraint(
        _CONSTRAINT, "source_authorships", ["source_publication_id", "author_position"]
    )
