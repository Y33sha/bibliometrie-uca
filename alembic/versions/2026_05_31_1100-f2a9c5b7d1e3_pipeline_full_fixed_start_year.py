"""config : pipeline_years_full (offset) → pipeline_start_year_full (année absolue)

Passe la fenêtre du mode `full` d'un offset glissant (année courante − N) à
une **année de départ absolue** (ancre fixe). Rétention cumulative : `full`
re-moissonne tout l'historique depuis l'ancre au lieu de laisser la fenêtre
glisser et d'abandonner les vieilles publis. Ancre = 2017 (fusion fondatrice
de l'UCA, cohérent avec la borne basse de l'extraction theses.fr).

`pipeline_years_weekly` reste un offset (fenêtre récente glissante, voulu).

Revision ID: f2a9c5b7d1e3
Revises: d4e8a1f6c3b7
Create Date: 2026-05-31 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2a9c5b7d1e3"
down_revision: str | Sequence[str] | None = "d4e8a1f6c3b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE config
        SET key = 'pipeline_start_year_full',
            value = '2017'::jsonb,
            description = 'Mode full/monthly : extraire depuis cette année (incluse) jusqu''à l''année courante. Année absolue (ancre fixe), pas un offset — rétention cumulative.'
        WHERE key = 'pipeline_years_full'
        """
    )


def downgrade() -> None:
    # Reconstruit un offset équivalent à l'ancre, figé à la date du downgrade.
    op.execute(
        """
        UPDATE config
        SET key = 'pipeline_years_full',
            value = to_jsonb(EXTRACT(YEAR FROM CURRENT_DATE)::int - (value #>> '{}')::int),
            description = 'Mode full/monthly : extraire depuis (année courante - N)'
        WHERE key = 'pipeline_start_year_full'
        """
    )
