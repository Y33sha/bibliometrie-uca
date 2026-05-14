"""source_publications : add updated_at column

Phase 2 du chantier `DATA_separer-matching-normalisation.md` :
support du refresh sélectif des publications canoniques dont au moins
un `source_publication` a été modifié depuis le dernier refresh. Sans
cette colonne, la phase publications devrait soit refresh toutes les
pubs (coûteux), soit casser le rattachement au re-normalize (risque
de doublons).

`updated_at` utilise `clock_timestamp()` (wall-clock) et non `now()`
(= `transaction_timestamp()`, figé dans une transaction). Justification :
la valeur est comparée à `publications.updated_at` pour détecter les
modifications post-refresh ; `now()` rendrait la comparaison fausse en
transaction unique (tests d'intégration notamment). `clock_timestamp()`
avance toujours, même au sein d'un statement, ce qui garantit l'ordre
strict sp/pub indépendamment du modèle de transaction.

`publications.updated_at` reste sur `now()` — pas de comparaison
transactionnelle dans son usage.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-14 13:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_publications",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("source_publications", "updated_at")
