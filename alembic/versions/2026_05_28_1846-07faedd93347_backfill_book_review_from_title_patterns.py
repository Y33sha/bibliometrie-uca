"""Backfill book_review depuis les patterns de titre

Reclasse les publications existantes vers `doc_type = 'book_review'` sur la
base des deux règles introduites dans `domain/publications/correction.py` :

- `TITLE_ISBN_TO_BOOK_REVIEW` : titre portant la mention « ISBN » ou un
  numéro ISBN-13 nu.
- `TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW` : titre terminé par « (19|20)YY,
  N p[.|ages] » (référence biblio injectée dans le champ titre, forme
  classique d'une recension).

Whitelist `{article, review, other}` dans les deux cas (mêmes raisons que
les règles Python : `book` exclu — un livre réel peut porter sa propre
ref biblio ou ISBN dans le titre, faux positif sinon ; `book_chapter`
idem ; `book_review` no-op naturel).

L'ordre des UPDATE reproduit l'ordre de la cascade Python (ISBN d'abord) :
le second UPDATE ne retouchera pas les publis déjà passées en `book_review`
car la whitelist les exclut.

SQL pur, conforme à la règle « migration = SQL pur, pas d'import code
applicatif » (la duplication entre `domain/` et la migration est assumée).

Revision ID: 07faedd93347
Revises: 00da0bf27d36
Create Date: 2026-05-28 18:46:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "07faedd93347"
down_revision: str | Sequence[str] | None = "00da0bf27d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Pattern ISBN — mention textuelle « ISBN » (mot entier) ou préfixe
    #    ISBN-13 nu (97[89] suivi de 10–17 caractères chiffres/espaces/tirets).
    #    `\m` / `\M` = word boundaries en regex POSIX Postgres.
    op.execute(
        r"""
        UPDATE public.publications
        SET doc_type = 'book_review',
            meta = jsonb_set(
                COALESCE(meta, '{}'::jsonb),
                '{doc_type_corrected_by}',
                '"TITLE_ISBN_TO_BOOK_REVIEW"'::jsonb,
                true
            )
        WHERE title ~* '\misbn\M|\m97[89][- 0-9]{10,17}\M'
          AND doc_type::text IN ('article', 'review', 'other')
        """
    )

    # 2. Pattern année + nb pages en fin de titre.
    op.execute(
        r"""
        UPDATE public.publications
        SET doc_type = 'book_review',
            meta = jsonb_set(
                COALESCE(meta, '{}'::jsonb),
                '{doc_type_corrected_by}',
                '"TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW"'::jsonb,
                true
            )
        WHERE title ~* '(19|20)[0-9]{2}[[:space:],.]+[0-9]{1,4}[[:space:]]*(pp|pages?|p)\.?[[:space:]]*$'
          AND doc_type::text IN ('article', 'review', 'other')
        """
    )


def downgrade() -> None:
    # Le doc_type d'origine n'est pas conservé : impossible de restaurer
    # la valeur d'avant (article / review / other selon le cas) sans
    # rejouer un audit. Rollback non implémenté.
    raise NotImplementedError(
        "Backfill book_review : doc_type d'origine non conservé, rollback non implémenté"
    )
