"""Revues : les ISSN rejetés comprennent les ISSN périmés

Met à jour le commentaire de `journals.rejected_issns` : la colonne reçoit aussi des ISSN valides mais périmés (autre support comme le CD-ROM, ISSN annulé, titre précédent ou suivant), qui servent au rapprochement.

Revision ID: a3c8e1f5d902
Revises: f1a7c3d9b204
Create Date: 2026-09-15 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3c8e1f5d902"
down_revision: str | Sequence[str] | None = "f1a7c3d9b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
COMMENT ON COLUMN public.journals.rejected_issns IS 'ISSN rejetés des colonnes issn, eissn et issnl : fautifs, tels que reçus des sources, ou périmés (autre support comme le CD-ROM, ISSN annulé, titre précédent ou suivant). Ils servent au rapprochement ; la vérification dans le Sudoc tente de corriger les fautifs.';
"""

_DOWNGRADE = r"""
COMMENT ON COLUMN public.journals.rejected_issns IS 'ISSN invalides reçus des sources pour cette revue, tels que reçus. La vérification dans le Sudoc tente leur correction.';
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
