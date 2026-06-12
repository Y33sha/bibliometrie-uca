"""place_name_forms : vider les formes non-country (avant re-seed ROR)

Les noms d'institutions seedés empiriquement (n-grammes d'universités, 1re et 2e
fournées) sont remplacés par un seed propre depuis ROR (oneshot
`seed_place_names_from_ror`). On vide d'abord toutes les formes non-country ;
les `addresses.countries` déjà résolues sont conservées (re-confirmées au prochain
run de detect_place).

Les anciennes migrations de seed restent dans l'historique (chaîne Alembic) ;
leur data est neutralisée ici.

Revision ID: c8f3a6b1e4d7
Revises: b9d4e7a2f5c8
Create Date: 2026-06-12 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8f3a6b1e4d7"
down_revision: str | Sequence[str] | None = "b9d4e7a2f5c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM place_name_forms WHERE kind <> 'country'")


def downgrade() -> None:
    # Les formes supprimées venaient des migrations de seed amont ; leur
    # restauration passe par un re-seed (oneshot ROR), pas par ce downgrade.
    pass
