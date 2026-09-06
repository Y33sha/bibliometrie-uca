"""Décrit le cycle de vie d'une ligne `staging` en commentaire de table

Les trois états d'une ligne — à traiter, normalisée, introuvable — se lisaient dans la
documentation du pipeline, qui décrit une logique et non des colonnes. Le commentaire de table
les met là où vivent les sémantiques du schéma.

Revision ID: f3b8d24e7a19
Revises: e2f5a71c93d8
Create Date: 2026-09-06 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3b8d24e7a19"
down_revision: str | Sequence[str] | None = "e2f5a71c93d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENTAIRE = (
    "Documents moissonnés, en transit vers les tables sources. Trois états : à traiter "
    "(processed FALSE, raw_data porte le payload de la source), normalisée (processed "
    "TRUE, raw_data vidé), introuvable (processed TRUE, not_found_at horodaté, raw_data "
    "jamais peuplé). Le dernier est posé par la phase fetch_missing quand HAL ne rend "
    "pas un document demandé par hal-id ou NNT."
)


def upgrade() -> None:
    commentaire = _COMMENTAIRE.replace("'", "''")
    op.execute(f"COMMENT ON TABLE staging IS '{commentaire}'")  # noqa: S608


def downgrade() -> None:
    op.execute("COMMENT ON TABLE staging IS NULL")
