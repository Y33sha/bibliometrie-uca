"""publications.unpaywall_checked_at : staleness de l'enrichissement OA

La phase `oa_status` interrogeait Unpaywall pour **tous** les DOI à chaque run
(~107k), alors que 97 % ont OpenAlex comme source (oa_status déjà dérivé
d'Unpaywall) et que les corrections sont déjà appliquées par les full précédents
(0,36 % de changements/run). >6600 s pour quasi rien.

On rend la phase incrémentale : `unpaywall_checked_at` date la derniere
verification. On ne (re)verifie que les publis jamais verifiees (1× meme les
gold/diamond/hybrid, car OpenAlex se trompe parfois) ou dont le statut est
changeable (hors STABLE_OA_STATUSES) et perime (> N jours). Cap par run pour
lisser la charge.

Revision ID: e3f7b2d9c5a8
Revises: d8b3f5a2c9e6
Create Date: 2026-06-13 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3f7b2d9c5a8"
down_revision: str | Sequence[str] | None = "d8b3f5a2c9e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE publications ADD COLUMN unpaywall_checked_at timestamptz")
    # Sert l'ORDER BY unpaywall_checked_at NULLS FIRST LIMIT du fetch (jamais
    # vérifiés d'abord, puis les plus périmés). Partiel : seules les publis à DOI
    # sont concernées.
    op.execute(
        "CREATE INDEX idx_pub_unpaywall_checked "
        "ON publications (unpaywall_checked_at NULLS FIRST) WHERE doi IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pub_unpaywall_checked")
    op.execute("ALTER TABLE publications DROP COLUMN IF EXISTS unpaywall_checked_at")
