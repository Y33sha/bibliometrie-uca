"""`hr_records` sans fonction, service ni dates : les périodes de présence sont dans `hr_periods`

Revision ID: 79fc60e8c39d
Revises: d34e51fb8697
Create Date: 2026-11-02 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "79fc60e8c39d"
down_revision: str | Sequence[str] | None = "d34e51fb8697"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("idx_hr_records_department", table_name="hr_records", schema="persons")
    for column in ("role_title", "department_name", "start_date", "end_date"):
        op.drop_column("hr_records", column, schema="persons")


def downgrade() -> None:
    op.add_column("hr_records", sa.Column("role_title", sa.Text()), schema="persons")
    op.add_column("hr_records", sa.Column("department_name", sa.Text()), schema="persons")
    op.add_column("hr_records", sa.Column("start_date", sa.Date()), schema="persons")
    op.add_column("hr_records", sa.Column("end_date", sa.Date()), schema="persons")
    op.create_index(
        "idx_hr_records_department", "hr_records", ["department_name"], schema="persons"
    )
