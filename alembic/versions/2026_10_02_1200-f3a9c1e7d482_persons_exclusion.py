"""Motif d'exclusion d'une personne : fausse entité ou hors périmètre

La colonne `persons.exclusion` porte le motif. Une personne `rejected` reçoit le motif `not_a_person`, puis la colonne `rejected` est supprimée.

Revision ID: f3a9c1e7d482
Revises: d8a4c2f7b915
Create Date: 2026-10-02 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a9c1e7d482"
down_revision: str | Sequence[str] | None = "d8a4c2f7b915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
CREATE TYPE public.person_exclusion AS ENUM ('not_a_person', 'out_of_perimeter');
ALTER TABLE public.persons ADD COLUMN exclusion public.person_exclusion;
UPDATE public.persons SET exclusion = 'not_a_person' WHERE rejected;
ALTER TABLE public.persons DROP COLUMN rejected;
COMMENT ON COLUMN public.persons.exclusion IS 'Motif d''exclusion décidé à la main : not_a_person (fausse entité), out_of_perimeter (personne réelle rattachée au périmètre par erreur). Nul pour une personne retenue.';
"""

_DOWNGRADE = r"""
ALTER TABLE public.persons ADD COLUMN rejected boolean DEFAULT false;
UPDATE public.persons SET rejected = (exclusion IS NOT NULL);
ALTER TABLE public.persons DROP COLUMN exclusion;
DROP TYPE public.person_exclusion;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
