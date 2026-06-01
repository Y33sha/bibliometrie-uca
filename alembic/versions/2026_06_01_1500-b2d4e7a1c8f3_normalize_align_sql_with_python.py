"""normalize : aligne `normalize_name_form` SQL sur `normalize_text` Python

Trois changements sur la fonction PL/pgSQL :

1. Fix d'un bug latent du `translate` originel : 9 tirets dans le `to` pour
   seulement 7 caractères-tirets en `from`, ce qui décalait le mapping des
   apostrophes/guillemets typographiques (`U+2018`, `U+2019`, `U+201C`, `U+201D`).
   Bug sans conséquence sur le résultat final (le `regexp_replace` ramenait
   tout à des espaces), mais trompeur à relire.

2. Ajout d'une étape `translate` pour les chiffres exposants (`U+2070`,
   `U+00B9`, `U+00B2`, `U+00B3`, `U+2074..2079`) et indices (`U+2080..2089`).
   Côté Python, `NFKD` les décompose en chiffres ASCII ; côté SQL, `unaccent`
   ne les couvrait pas et le regex `[^a-z0-9]+` les transformait en espaces.

3. Ajout de `REPLACE` pour les fractions vulgaires (`U+00BC`, `U+00BD`,
   `U+00BE`, `U+2150..215E`). NFKD côté Python les décompose en
   `<num>⁄<den>`, l'`encode("ascii", "ignore")` supprime le `FRACTION SLASH`
   et colle les chiffres ; on reproduit cette concaténation directement.

Le superscript-minus (`U+207B`) est intégré au translate étape 2 mais sans
correspondance dans le `to` : `translate` supprime alors le caractère, ce
qui aligne le comportement Python (`encode ASCII ignore` le supprime).

Pas de recompute des colonnes `_normalized` : elles sont peuplées par
`domain.normalize.normalize_text` au pipeline, donc déjà correctes vis-à-vis
de la SQL nouvellement alignée.

Revision ID: b2d4e7a1c8f3
Revises: a7e3f1c9b5d2
Create Date: 2026-06-01 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2d4e7a1c8f3"
down_revision: str | Sequence[str] | None = "a7e3f1c9b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FN_ALIGNED = r"""
CREATE OR REPLACE FUNCTION public.normalize_name_form(input text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = public, pg_temp
AS $fn$
DECLARE
    s text := input;
BEGIN
    IF s IS NULL THEN
        RETURN NULL;
    END IF;

    s := replace(s, E'¼', '14');
    s := replace(s, E'½', '12');
    s := replace(s, E'¾', '34');
    s := replace(s, E'⅐', '17');
    s := replace(s, E'⅑', '19');
    s := replace(s, E'⅒', '110');
    s := replace(s, E'⅓', '13');
    s := replace(s, E'⅔', '23');
    s := replace(s, E'⅕', '15');
    s := replace(s, E'⅖', '25');
    s := replace(s, E'⅗', '35');
    s := replace(s, E'⅘', '45');
    s := replace(s, E'⅙', '16');
    s := replace(s, E'⅚', '56');
    s := replace(s, E'⅛', '18');
    s := replace(s, E'⅜', '38');
    s := replace(s, E'⅝', '58');
    s := replace(s, E'⅞', '78');

    s := translate(s,
        E'‐‑‒–—―­‘’‚′“”',
        E'-------\x27\x27\x27\x27""'
    );

    s := translate(s,
        E'⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉⁻',
        '01234567890123456789'
    );

    RETURN trim(regexp_replace(
        unaccent(lower(trim(s))),
        '[^a-z0-9]+', ' ', 'g'
    ));
END;
$fn$;
"""


_FN_LEGACY = r"""
CREATE OR REPLACE FUNCTION public.normalize_name_form(text)
RETURNS text
LANGUAGE sql IMMUTABLE
SET search_path = public, pg_temp
AS $fn$
  SELECT trim(regexp_replace(
    unaccent(lower(trim(
      translate($1,
        E'‐‑‒–—―­‘’‚′“”',
        E'---------\x27\x27\x27\x27""')
    ))),
    '[^a-z0-9]+', ' ', 'g'));
$fn$;
"""


def upgrade() -> None:
    op.execute(_FN_ALIGNED)


def downgrade() -> None:
    op.execute(_FN_LEGACY)
