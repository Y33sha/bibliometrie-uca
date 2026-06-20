"""oa_type : valeur 'embargoed' + source_publications.embargo_until

Statut OA intermédiaire pour les dépôts HAL sous embargo : le fichier existe mais
l'accès est légalement différé jusqu'à une date (`ref[@type='file']/date/@notBefore`
du TEI). `embargoed` se range entre `green` et `closed` dans `OA_RANK` (côté domaine,
pas dans l'ordre de déclaration de l'enum). `embargo_until` porte la date de levée
(NULL = pas d'embargo connu) ; à l'échéance, une règle de correction promeut
`embargoed → green`.

Revision ID: b7e3f9a1c4d8
Revises: d4a9c1e7f3b2
Create Date: 2026-06-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e3f9a1c4d8"
down_revision: str | Sequence[str] | None = "d4a9c1e7f3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `ALTER TYPE ... ADD VALUE` est non transactionnel : isolé en autocommit_block.
    # La valeur n'est pas utilisée dans cette migration (juste ajoutée), donc aucun
    # SET DEFAULT / cast ne dépend de son commit ici.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE public.oa_type ADD VALUE IF NOT EXISTS 'embargoed'")
    op.add_column(
        "source_publications",
        sa.Column("embargo_until", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    # PostgreSQL ne sait pas retirer une valeur d'enum (cf. migration 0020 sur
    # structure_type pour la recréation complète si jamais nécessaire) ; on retire
    # seulement la colonne.
    op.drop_column("source_publications", "embargo_until")
