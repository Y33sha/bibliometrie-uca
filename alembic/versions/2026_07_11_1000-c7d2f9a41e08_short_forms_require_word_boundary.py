"""structure_name_forms : forme courte ⇒ is_word_boundary garanti

Une forme de nom courte (<= 6 caractères sur le texte normalisé) matchée en sous-chaîne
produit trop de faux positifs (« ica » dans « africa ») : elle doit exiger une frontière
de mot. L'invariant « forme courte ⇒ is_word_boundary » est établi dans la donnée :
backfill des formes courtes existantes vers `is_word_boundary = true`, puis contrainte
`CHECK` qui l'impose.

Revision ID: c7d2f9a41e08
Revises: b3f6a1d29c47
Create Date: 2026-07-11 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7d2f9a41e08"
down_revision: str | Sequence[str] | None = "b3f6a1d29c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Seuil aligné sur `domain.structures.name_forms.SHORT_FORM_MAX_LENGTH` (dupliqué ici :
# une migration ne peut pas importer de code applicatif).
_UPGRADE = """
UPDATE public.structure_name_forms
   SET is_word_boundary = true
 WHERE char_length(form_text) <= 6
   AND NOT is_word_boundary;

ALTER TABLE public.structure_name_forms
    ADD CONSTRAINT ck_structure_name_forms_short_word_boundary
    CHECK (char_length(form_text) > 6 OR is_word_boundary);
"""

_DOWNGRADE = """
ALTER TABLE public.structure_name_forms
    DROP CONSTRAINT IF EXISTS ck_structure_name_forms_short_word_boundary;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
