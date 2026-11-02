"""Matricule et attributs RH de la personne, périodes de présence dans les unités

`hr_records` reçoit le matricule SIHAM, la catégorie de personnel, le statut, le corps et le grade. `persons.hr_periods` réunit les périodes de présence d'une personne dans une unité. `structure_id` y est renseigné quand l'unité est un laboratoire de `structures`. Chaque fiche RH existante devient une période, sur son service et ses dates.

Revision ID: d34e51fb8697
Revises: b8d3f1a6c4e2
Create Date: 2026-11-02 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d34e51fb8697"
down_revision: str | Sequence[str] | None = "b8d3f1a6c4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_records", sa.Column("siham_id", sa.Text()), schema="persons")
    op.add_column("hr_records", sa.Column("staff_category", sa.Text()), schema="persons")
    op.add_column("hr_records", sa.Column("employment_status", sa.Text()), schema="persons")
    op.add_column("hr_records", sa.Column("corps", sa.Text()), schema="persons")
    op.add_column("hr_records", sa.Column("grade", sa.Text()), schema="persons")
    op.create_unique_constraint(
        "hr_records_siham_id_key", "hr_records", ["siham_id"], schema="persons"
    )

    op.create_table(
        "hr_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "person_id",
            sa.Integer(),
            sa.ForeignKey("persons.persons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("unit_label", sa.Text(), nullable=False),
        sa.Column(
            "structure_id",
            sa.Integer(),
            sa.ForeignKey("structures.structures.id", ondelete="SET NULL"),
        ),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "person_id",
            "unit_label",
            "start_date",
            name="hr_periods_person_unit_start_key",
            postgresql_nulls_not_distinct=True,
        ),
        schema="persons",
    )
    op.create_index("idx_hr_periods_structure_id", "hr_periods", ["structure_id"], schema="persons")

    op.execute("""
        INSERT INTO persons.hr_periods (person_id, unit_label, start_date, end_date)
        SELECT person_id, department_name, start_date, end_date
        FROM persons.hr_records
        WHERE department_name IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_table("hr_periods", schema="persons")
    op.drop_constraint("hr_records_siham_id_key", "hr_records", schema="persons")
    for column in ("grade", "corps", "employment_status", "staff_category", "siham_id"):
        op.drop_column("hr_records", column, schema="persons")
