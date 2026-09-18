"""Revues : les ISSN rejetés sont ceux de la même revue

Met à jour le commentaire de `journals.rejected_issns` : la colonne garde les ISSN de la revue hors de ses colonnes, supplément compris, et sert à la fusion des revues. Les ISSN d'une autre publication en sortent.

Remet à vérifier toutes les revues vérifiées dans le Sudoc : la vérification suivante reclasse leurs ISSN rejetés selon ces règles. La fusion des revues qui partagent un ISSN rejeté porte sur les seules revues vérifiées, donc elle attend ce reclassement. La remise à vérifier ne se défait pas.

Revision ID: c5e9a2d4f817
Revises: d7b2f4a9c1e6
Create Date: 2026-09-18 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5e9a2d4f817"
down_revision: str | Sequence[str] | None = "d7b2f4a9c1e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
COMMENT ON COLUMN public.journals.rejected_issns IS 'ISSN de la revue hors des colonnes issn, eissn et issnl : fautifs, tels que reçus des sources, ou valides (autre support comme le CD-ROM, ISSN annulé, titre précédent ou suivant, supplément). Ils servent au rapprochement et à la fusion des revues ; la vérification dans le Sudoc tente de corriger les fautifs.';
UPDATE public.journals SET sudoc_checked_at = NULL WHERE sudoc_checked_at IS NOT NULL;
"""

_DOWNGRADE = r"""
COMMENT ON COLUMN public.journals.rejected_issns IS 'ISSN rejetés des colonnes issn, eissn et issnl : fautifs, tels que reçus des sources, ou périmés (autre support comme le CD-ROM, ISSN annulé, titre précédent ou suivant). Ils servent au rapprochement ; la vérification dans le Sudoc tente de corriger les fautifs.';
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
