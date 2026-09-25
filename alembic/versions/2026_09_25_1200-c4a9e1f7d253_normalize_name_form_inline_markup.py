"""normalize_name_form retire sans espace les balises de mise en forme

Une balise de mise en forme (`<sub>`, `<i>`, MathML) disparaît et garde entier le mot qu'elle coupe : `CO<sub>2</sub>` donne `co2`, comme `normalize_text` côté Python. Les autres balises deviennent un espace.

Revision ID: c4a9e1f7d253
Revises: b3f6d2a8c417
Create Date: 2026-09-25 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4a9e1f7d253"
down_revision: str | Sequence[str] | None = "b3f6d2a8c417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INLINE_TAGS = (
    "sub|sup|i|b|em|strong|u|span|small|tt|sc|scp|italic|bold|underline|monospace|overline|roman|strike"
    "|math|mi|mn|mo|ms|mtext|mrow|msub|msup|msubsup|mfrac|msqrt|mroot|mover|munder|munderover"
    "|mstyle|mspace|mpadded|mphantom|mfenced|menclose|semantics|inline-formula"
)

_MARKUP_UPGRADE = rf"""
    -- Retrait des balises MathML/HTML. Une balise de mise en forme (<sub>, <i>, <mml:mi> …)
    -- disparaît : CO<sub>2</sub> donne CO2. Les autres balises deviennent un espace.
    -- Premier caractère = lettre ou '/' : les indices de Miller <111>/<110> (cristallographie)
    -- restent dans le texte.
    s := regexp_replace(s, '</?([A-Za-z][A-Za-z0-9.-]*:)?({_INLINE_TAGS})(\s[^>]*|/)?>', '', 'gi');
    s := regexp_replace(s, '</?[A-Za-z][^>]*>', ' ', 'g');
"""

_MARKUP_DOWNGRADE = r"""
    -- Retrait des balises MathML/HTML (<i>, <sub>, <mml:*> …) en entier.
    -- Premier caractère = lettre ou '/' : préserve les indices de Miller
    -- <111>/<110> (cristallographie), qui sont du contenu, pas du markup.
    s := regexp_replace(s, '</?[A-Za-z][^>]*>', ' ', 'g');
"""

_FUNCTION = r"""
CREATE OR REPLACE FUNCTION public.normalize_name_form(input text)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    s text := input;
BEGIN
    IF s IS NULL THEN
        RETURN NULL;
    END IF;
__MARKUP__
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

    -- Chiffres exposants/indices → chiffres ASCII (attachés). L'exposant moins `⁻`
    -- tombe dans le passage [^a-z0-9] → espace.
    s := translate(s,
        E'⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉',
        '01234567890123456789'
    );

    RETURN trim(regexp_replace(
        unaccent(lower(trim(s))),
        '[^a-z0-9]+', ' ', 'g'
    ));
END;
$function$
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_FUNCTION.replace("__MARKUP__", _MARKUP_UPGRADE))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(_FUNCTION.replace("__MARKUP__", _MARKUP_DOWNGRADE))
