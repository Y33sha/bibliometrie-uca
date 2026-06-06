"""normalize : retirer les balises MathML/HTML des titres + renormaliser

`normalize_name_form` (SQL, alignée sur `domain.normalize.normalize_text` Python)
retire désormais les balises `<...>` **avant** toute autre étape. Sans ça, le nom
de balise (`mml`, `i`, `sub`…) subsistait comme texte après le passage
`[^a-z0-9] → espaces` et polluait le `title_normalized` — donc le dédoublonnage
par titre, certaines sources exposant les titres avec balises et d'autres non.

Le premier caractère du tag doit être une lettre (ou `/`) : audit des titres bruts
(`source_publications.title`) → les seuls `<...>` non-balise observés sont des
indices de Miller cristallographiques (`<111>`, `<110>`, `{100}<011>`), qui sont du
contenu et doivent survivre. `</?[A-Za-z][^>]*>` les préserve.

Backfill : recalcul de `title_normalized` sur les lignes dont le titre porte une
balise (≈1256 publications ; 0 journal). Les autres colonnes `_normalized` (formes
de noms) ne portent jamais de balise → pas touchées.

Revision ID: c4f8a1e6b3d9
Revises: e8f1a3c5d7b9
Create Date: 2026-06-06 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f8a1e6b3d9"
down_revision: str | Sequence[str] | None = "e8f1a3c5d7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FN_WITH_TAG_STRIP = r"""
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


_FN_WITHOUT_TAG_STRIP = r"""
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

_BACKFILL = r"""
UPDATE publications SET title_normalized = public.normalize_name_form(title)
WHERE title ~ '</?[A-Za-z][^>]*>';

UPDATE journals SET title_normalized = public.normalize_name_form(title)
WHERE title ~ '</?[A-Za-z][^>]*>';
"""


def upgrade() -> None:
    op.execute(_FN_WITH_TAG_STRIP)
    op.execute(_BACKFILL)


def downgrade() -> None:
    # Restaure la fonction sans retrait de balises. Le `title_normalized` déjà
    # nettoyé n'est pas re-pollué (la donnée nettoyée reste valide).
    op.execute(_FN_WITHOUT_TAG_STRIP)
