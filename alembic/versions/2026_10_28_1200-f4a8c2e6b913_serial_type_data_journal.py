"""Ajoute la valeur 'data_journal' à l'enum serial_type et type ainsi quatre revues de données

Une revue de données publie des data papers, que les sources typent `article`. La règle de correction `SERIAL_TYPE_DATA_JOURNAL_TO_DATA_PAPER` les retype d'après le type de la revue. Les quatre revues se reconnaissent à leurs ISSN. Leur type rejoint `manual_fields`, comme une saisie de l'administration. Un type déjà saisi à la main reste en l'état.

Revision ID: f4a8c2e6b913
Revises: c3d9a7e1f5b2
Create Date: 2026-10-28 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4a8c2e6b913"
down_revision: str | Sequence[str] | None = "c3d9a7e1f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_JOURNAL_ISSNS = {
    "Scientific Data": ("2052-4463",),
    "Data in Brief": ("2352-3409",),
    "Earth System Science Data": ("1866-3508", "1866-3516"),
    "Biodiversity Data Journal": ("1314-2828", "1314-2836"),
}


def upgrade() -> None:
    # La valeur ajoutée s'emploie seulement après la validation de la transaction qui l'ajoute.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE public.serial_type ADD VALUE IF NOT EXISTS 'data_journal' AFTER 'journal'"
        )
    issns = ", ".join(f"'{issn}'" for group in _DATA_JOURNAL_ISSNS.values() for issn in group)
    op.execute(f"""
        UPDATE publishing.serials
        SET serial_type = 'data_journal',
            manual_fields = array_append(manual_fields, 'serial_type')
        WHERE id IN (SELECT serial_id FROM publishing.serial_issns WHERE issn IN ({issns}))
          AND NOT 'serial_type' = ANY(manual_fields)
    """)


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade ramène les revues de données à
    # 'journal' et laisse la valeur dans le type, inutilisée.
    op.execute("""
        UPDATE publishing.serials SET serial_type = 'journal' WHERE serial_type = 'data_journal'
    """)
