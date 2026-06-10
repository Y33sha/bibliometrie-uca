"""normalize : lettres latines autonomes, fractions espacées, I turc + backfill

`domain.normalize.normalize_text` (Python, référence) ne supprime plus les
lettres latines autonomes (ß, ø, ł, đ, ð, þ...) : elles sont translittérées
comme le fait `unaccent`, au lieu d'être avalées par `encode("ascii","ignore")`
(qui collait les voisins : "Meyerhofstraße" → "meyerhofstrae"). Deux autres
changements de comportement, alignés ici côté SQL :

- Fractions vulgaires → chiffres **espacés** : `¼` donne `1 4`, comme un `1/4`
  tapé à la main (le slash devient une espace). Avant : `14` (collé), qui ne
  dédupliquait pas avec `1/4`.
- `İ` (I turc avec point) translittéré en `i`. PostgreSQL `lower()`+`unaccent`
  le perdait entièrement ("İstanbul" → "stanbul").
- Exposant moins `⁻` → espace (retiré du `translate`), cohérent avec un `-`
  tapé à la main : `10⁻³` → `10 3`.

Les lettres latines autonomes étaient déjà gérées côté SQL par `unaccent` : la
fonction est inchangée sur ce point. Seuls les trois deltas ci-dessus modifient
`normalize_name_form`.

Backfill : recalcul conditionnel des colonnes `_normalized` dont la source brute
est co-stockée (uniquement les lignes qui changent). Les tables de formes de noms
(`*_name_forms`, `structure_name_forms.form_text`) ne stockent que la valeur
normalisée — pas le brut : elles ne sont pas backfillables in-place et relèvent
d'un rerun du pipeline.

Revision ID: e2c7a9f4b1d6
Revises: c6d0f3a2b5e8
Create Date: 2026-06-10 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2c7a9f4b1d6"
down_revision: str | Sequence[str] | None = "c6d0f3a2b5e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FN_NEW = r"""
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

    -- Retrait des balises MathML/HTML (<i>, <sub>, <mml:*> …) en entier.
    -- Premier caractère = lettre ou '/' : préserve les indices de Miller
    -- <111>/<110> (cristallographie), qui sont du contenu, pas du markup.
    s := regexp_replace(s, '</?[A-Za-z][^>]*>', ' ', 'g');

    -- I turc avec point : PG lower()+unaccent le perd ("İstanbul" → "stanbul").
    s := replace(s, E'İ', 'i');

    -- Fractions vulgaires → chiffres espacés (comme "1/4" tapé à la main).
    s := replace(s, E'¼', '1 4');
    s := replace(s, E'½', '1 2');
    s := replace(s, E'¾', '3 4');
    s := replace(s, E'⅐', '1 7');
    s := replace(s, E'⅑', '1 9');
    s := replace(s, E'⅒', '1 10');
    s := replace(s, E'⅓', '1 3');
    s := replace(s, E'⅔', '2 3');
    s := replace(s, E'⅕', '1 5');
    s := replace(s, E'⅖', '2 5');
    s := replace(s, E'⅗', '3 5');
    s := replace(s, E'⅘', '4 5');
    s := replace(s, E'⅙', '1 6');
    s := replace(s, E'⅚', '5 6');
    s := replace(s, E'⅛', '1 8');
    s := replace(s, E'⅜', '3 8');
    s := replace(s, E'⅝', '5 8');
    s := replace(s, E'⅞', '7 8');

    s := translate(s,
        E'‐‑‒–—―­‘’‚′“”',
        E'-------\x27\x27\x27\x27""'
    );

    -- Chiffres exposants/indices → chiffres ASCII (attachés). L'exposant moins
    -- `⁻` n'est plus listé : il tombe dans le passage [^a-z0-9] → espace.
    s := translate(s,
        E'⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉',
        '01234567890123456789'
    );

    RETURN trim(regexp_replace(
        unaccent(lower(trim(s))),
        '[^a-z0-9]+', ' ', 'g'
    ));
END;
$fn$;
"""


_FN_OLD = r"""
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

    s := regexp_replace(s, '</?[A-Za-z][^>]*>', ' ', 'g');

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


# Backfill : uniquement les colonnes dont la source brute est co-stockée, et
# seulement les lignes qui changent (IS DISTINCT FROM). Source NULL ignorée
# pour ne jamais violer une contrainte NOT NULL.
_BACKFILL = r"""
UPDATE addresses SET normalized_text = public.normalize_name_form(raw_text)
WHERE raw_text IS NOT NULL
  AND normalized_text IS DISTINCT FROM public.normalize_name_form(raw_text);

UPDATE persons SET last_name_normalized = public.normalize_name_form(last_name)
WHERE last_name IS NOT NULL
  AND last_name_normalized IS DISTINCT FROM public.normalize_name_form(last_name);

UPDATE persons SET first_name_normalized = public.normalize_name_form(first_name)
WHERE first_name IS NOT NULL
  AND first_name_normalized IS DISTINCT FROM public.normalize_name_form(first_name);

UPDATE publications SET title_normalized = public.normalize_name_form(title)
WHERE title IS NOT NULL
  AND title_normalized IS DISTINCT FROM public.normalize_name_form(title);

UPDATE journals SET title_normalized = public.normalize_name_form(title)
WHERE title IS NOT NULL
  AND title_normalized IS DISTINCT FROM public.normalize_name_form(title);

UPDATE publishers SET name_normalized = public.normalize_name_form(name)
WHERE name IS NOT NULL
  AND name_normalized IS DISTINCT FROM public.normalize_name_form(name);

UPDATE doi_prefixes
SET publisher_name_normalized = public.normalize_name_form(publisher_name_raw)
WHERE publisher_name_raw IS NOT NULL
  AND publisher_name_normalized
      IS DISTINCT FROM public.normalize_name_form(publisher_name_raw);

UPDATE doi_prefixes
SET client_name_normalized = public.normalize_name_form(client_name_raw)
WHERE client_name_raw IS NOT NULL
  AND client_name_normalized
      IS DISTINCT FROM public.normalize_name_form(client_name_raw);

UPDATE source_authorships
SET author_name_normalized = public.normalize_name_form(raw_author_name)
WHERE raw_author_name IS NOT NULL
  AND author_name_normalized
      IS DISTINCT FROM public.normalize_name_form(raw_author_name);
"""


def upgrade() -> None:
    op.execute(_FN_NEW)
    op.execute(_BACKFILL)


def downgrade() -> None:
    # Restaure la fonction précédente. Les colonnes déjà recalculées ne sont pas
    # re-polluées : la donnée corrigée reste valide sous l'ancienne fonction.
    op.execute(_FN_OLD)
