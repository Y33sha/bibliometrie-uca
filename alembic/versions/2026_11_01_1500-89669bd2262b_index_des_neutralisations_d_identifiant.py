"""Index partiel des contributions sources à identifiant neutralisé

Revision ID: 89669bd2262b
Revises: acdd16ac0007
Create Date: 2026-11-01 15:00:00.000000

L'arbitrage des identifiants relit à chaque run les neutralisations `misplaced`. L'index couvre les seules contributions sources à neutralisation, et contient la carte des neutralisations : la lecture se fait dans l'index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "89669bd2262b"
down_revision: str | Sequence[str] | None = "acdd16ac0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX source_contributions_neutralized_idx"
        " ON sources.source_contributions (id) INCLUDE (neutralized_identifiers)"
        " WHERE neutralized_identifiers IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX sources.source_contributions_neutralized_idx")
