"""Index partiel des informations du contributeur par compte HAL

Revision ID: e4a7c2d9b6f1
Revises: 5d2b8e4f7a19
Create Date: 2026-11-02 14:00:00.000000

Le contrôle des comptes HAL multiples lit les contributions sources de chaque compte HAL attribué à une personne. L'index permet de partir du compte, comme les index ORCID et IdRef.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4a7c2d9b6f1"
down_revision: str | Sequence[str] | None = "5d2b8e4f7a19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX contributor_information_hal_person_id_idx"
        " ON sources.contributor_information ((identifiers ->> 'hal_person_id'))"
        " WHERE identifiers ? 'hal_person_id'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX sources.contributor_information_hal_person_id_idx")
