"""Unicité des formes de nom de revue sans éditeur

Revision ID: c8e3f1a6d924
Revises: a4d9e2c7b318
Create Date: 2026-10-27 18:00:00.000000

La contrainte `(form_normalized, publisher_id)` passe en `NULLS NOT DISTINCT`.

Une forme sans éditeur est d'abord supprimée si aucun enregistrement source sans éditeur ne désigne sa revue. Parmi les doublons restants, la forme gardée est celle de la revue que choisit la recherche par forme de nom : revue à ISSN électronique actif d'abord, puis plus petit identifiant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8e3f1a6d924"
down_revision: str | Sequence[str] | None = "a4d9e2c7b318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM publishing.serial_name_forms f
        WHERE f.publisher_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM sources.source_records sr
              WHERE sr.serial_id = f.serial_id AND sr.publisher_id IS NULL
          )
    """)
    op.execute("""
        DELETE FROM publishing.serial_name_forms f
        USING (
            SELECT f.id,
                   row_number() OVER (
                       PARTITION BY f.form_normalized
                       ORDER BY EXISTS (
                                    SELECT 1 FROM publishing.serial_issns i
                                    WHERE i.serial_id = f.serial_id
                                      AND i.status = 'active' AND i.support = 'electronic'
                                ) DESC,
                                f.serial_id, f.id
                   ) AS rank
            FROM publishing.serial_name_forms f
            WHERE f.publisher_id IS NULL
        ) ranked
        WHERE f.id = ranked.id AND ranked.rank > 1
    """)
    op.execute(
        "ALTER TABLE publishing.serial_name_forms "
        "DROP CONSTRAINT uq_serial_name_forms_form_publisher"
    )
    op.execute(
        "ALTER TABLE publishing.serial_name_forms "
        "ADD CONSTRAINT uq_serial_name_forms_form_publisher "
        "UNIQUE NULLS NOT DISTINCT (form_normalized, publisher_id)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE publishing.serial_name_forms "
        "DROP CONSTRAINT uq_serial_name_forms_form_publisher"
    )
    op.execute(
        "ALTER TABLE publishing.serial_name_forms "
        "ADD CONSTRAINT uq_serial_name_forms_form_publisher UNIQUE (form_normalized, publisher_id)"
    )
