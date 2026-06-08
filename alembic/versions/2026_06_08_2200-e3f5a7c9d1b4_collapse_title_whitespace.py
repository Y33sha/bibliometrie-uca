"""backfill : collapse du whitespace parasite dans les titres de publications

Certains titres ont été ingérés avec du whitespace de mise en forme du markup
source (indentation + sauts de ligne autour des balises MathML/HTML), ex.
`…Multidrug-Resistant\n   <i>Escherichia coli</i>\n   ST131`. Audit : ~1025 /
66 882 titres concernés. C'est indésirable (cellules CSV multi-lignes, bruit à
l'affichage). La règle permanente est posée à la création (`clean_publication_title`,
cf. `domain/publications/metadata.py`) ; cette migration backfille le stock.

Collapse `\\s+` → un espace + trim. Les **balises HTML sont conservées** (la
regex ne touche que le whitespace). Idempotent (ne touche que les lignes qui
changent). Irréversible (le whitespace d'origine est perdu) → downgrade no-op.

Revision ID: e3f5a7c9d1b4
Revises: d2e4f6a8c1b3
Create Date: 2026-06-08 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3f5a7c9d1b4"
down_revision: str | Sequence[str] | None = "d2e4f6a8c1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        UPDATE publications
        SET title = trim(regexp_replace(title, '\s+', ' ', 'g'))
        WHERE trim(regexp_replace(title, '\s+', ' ', 'g')) IS DISTINCT FROM title
        """
    )


def downgrade() -> None:
    # Irréversible : le whitespace d'origine n'est pas conservé.
    pass
