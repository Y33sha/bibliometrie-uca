"""Libellé normalisé des sujets ; fonction SQL normalize_name_form() supprimée

`subjects.label_normalized` contient la forme de recherche du libellé, calculée par `normalize_text` à l'écriture du sujet. L'index trigram de la recherche est défini sur cette colonne. Le remplissage du stock passe par `normalize_name_form()`, puis la fonction est supprimée : la normalisation se calcule seulement en Python.

Revision ID: f85028312584
Revises: b3e7c1a9d508
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f85028312584"
down_revision: str | Sequence[str] | None = "b3e7c1a9d508"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FUNCTION = r"""
CREATE FUNCTION public.normalize_name_form(input text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    s text := input;
BEGIN
    IF s IS NULL THEN
        RETURN NULL;
    END IF;

    s := regexp_replace(s, '</?([A-Za-z][A-Za-z0-9.-]*:)?(sub|sup|i|b|em|strong|u|span|small|tt|sc|scp|italic|bold|underline|monospace|overline|roman|strike|math|mi|mn|mo|ms|mtext|mrow|msub|msup|msubsup|mfrac|msqrt|mroot|mover|munder|munderover|mstyle|mspace|mpadded|mphantom|mfenced|menclose|semantics|inline-formula)(\s[^>]*|/)?>', '', 'gi');
    s := regexp_replace(s, '</?[A-Za-z][^>]*>', ' ', 'g');

    s := replace(s, E'İ', 'i');

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

    s := translate(s,
        E'⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉',
        '01234567890123456789'
    );

    RETURN trim(regexp_replace(
        unaccent(lower(trim(s))),
        '[^a-z0-9]+', ' ', 'g'
    ));
END;
$$;
"""


def upgrade() -> None:
    op.execute("""
        ALTER TABLE publications.subjects ADD COLUMN label_normalized text;
        UPDATE publications.subjects SET label_normalized = public.normalize_name_form(label);
        ALTER TABLE publications.subjects ALTER COLUMN label_normalized SET NOT NULL;
        COMMENT ON COLUMN publications.subjects.label_normalized IS
            'Forme de recherche du libellé (normalize_text), servie par un index trigram.';

        DROP INDEX publications.subjects_label_norm_trgm_idx;
        CREATE INDEX subjects_label_normalized_trgm_idx
            ON publications.subjects USING gin (label_normalized public.gin_trgm_ops);

        DROP FUNCTION public.normalize_name_form(text);
    """)


def downgrade() -> None:
    op.execute(_FUNCTION)
    op.execute("""
        DROP INDEX publications.subjects_label_normalized_trgm_idx;
        CREATE INDEX subjects_label_norm_trgm_idx
            ON publications.subjects USING gin (public.normalize_name_form(label) public.gin_trgm_ops);
        ALTER TABLE publications.subjects DROP COLUMN label_normalized;
    """)
