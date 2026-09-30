"""Enregistrements sources : index sur le premier identifiant HAL

La clé de fusion HAL d'un enregistrement est le premier identifiant HAL qu'il liste. La réconciliation des publications cherche les enregistrements de même clé par égalité sur ce premier identifiant : l'index btree partiel sert cette recherche. L'index GIN sur le tableau entier des identifiants HAL est supprimé, aucune requête ne cherchant un identifiant par appartenance au tableau.

Revision ID: c5f1d8a3e604
Revises: b3e8a1d5f927
Create Date: 2026-09-30 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5f1d8a3e604"
down_revision: str | Sequence[str] | None = "b3e8a1d5f927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
DROP INDEX public.idx_source_pubs_hal_id;
CREATE INDEX idx_source_pubs_first_hal_id ON public.source_publications USING btree ((((external_ids -> 'hal_id'::text) ->> 0))) WHERE (((external_ids -> 'hal_id'::text) ->> 0) IS NOT NULL);
"""

_DOWNGRADE = r"""
DROP INDEX public.idx_source_pubs_first_hal_id;
CREATE INDEX idx_source_pubs_hal_id ON public.source_publications USING gin (((external_ids -> 'hal_id'::text)));
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
