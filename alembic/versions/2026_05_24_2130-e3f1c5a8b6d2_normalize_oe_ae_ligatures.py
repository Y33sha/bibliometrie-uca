"""normalize : recompute des colonnes _normalized affectées par œ/æ

`domain.normalize.normalize_text` ne gérait pas les ligatures `œ` et `æ` :
NFKD ne les décompose pas, et `encode("ascii", "ignore")` les avalait
silencieusement. Conséquence : un titre comme « œuvres » devenait
« uvres » au lieu de « oeuvres », divergent de la fonction SQL
`normalize_name_form` qui, via `unaccent`, gère correctement la ligature.

La fonction Python est désormais corrigée (mapping explicite `œ → oe`,
`æ → ae` dans `_UNICODE_TO_ASCII`). Cette migration recompute les
colonnes `_normalized` des tables ayant une source brute disponible et
contenant `œ`/`æ`, en utilisant la fonction SQL.

Tables sans source brute conservée (`country_name_forms`,
`publisher_name_forms`, `journal_name_forms`) : non traitées ici. Cas
marginal en pratique.

Revision ID: e3f1c5a8b6d2
Revises: b9a2c8d4e7f1
Create Date: 2026-05-24 21:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3f1c5a8b6d2"
down_revision: str | Sequence[str] | None = "b9a2c8d4e7f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE publications
        SET title_normalized = public.normalize_name_form(title)
        WHERE title ~* (U&'[\\0153\\00E6]');
        """
    )
    op.execute(
        """
        UPDATE journals
        SET title_normalized = public.normalize_name_form(title)
        WHERE title ~* (U&'[\\0153\\00E6]');
        """
    )
    op.execute(
        """
        UPDATE persons
        SET last_name_normalized = public.normalize_name_form(last_name)
        WHERE last_name ~* (U&'[\\0153\\00E6]');
        """
    )
    op.execute(
        """
        UPDATE persons
        SET first_name_normalized = public.normalize_name_form(first_name)
        WHERE first_name ~* (U&'[\\0153\\00E6]');
        """
    )
    op.execute(
        """
        UPDATE publishers
        SET name_normalized = public.normalize_name_form(name)
        WHERE name ~* (U&'[\\0153\\00E6]');
        """
    )
    op.execute(
        """
        UPDATE source_authorships
        SET author_name_normalized = public.normalize_name_form(raw_author_name)
        WHERE raw_author_name ~* (U&'[\\0153\\00E6]');
        """
    )
    op.execute(
        """
        UPDATE doi_prefixes
        SET publisher_name_normalized = public.normalize_name_form(publisher_name_raw)
        WHERE publisher_name_raw ~* (U&'[\\0153\\00E6]');
        """
    )


def downgrade() -> None:
    # Pas de downgrade : on ne sait pas régénérer l'erreur de normalisation
    # précédente, qui dépendait du caractère consommé (uvres vs oeuvres).
    pass
