-- Migration 059 : aligne normalize_name_form SQL avec le Python
-- Remplace les tirets et apostrophes Unicode par leur équivalent ASCII
-- AVANT le passage par unaccent/lower, pour éviter que encode("ascii", "ignore")
-- les supprime silencieusement et colle les mots.
-- Bug : "Abeywickrama‐Samarakoon" (U+2010) → "abeywickramasamarakoon" au lieu
-- de "abeywickrama samarakoon".

CREATE OR REPLACE FUNCTION normalize_name_form(text) RETURNS text AS $$
  SELECT trim(regexp_replace(
    unaccent(lower(trim(
      translate($1,
        E'\u2010\u2011\u2012\u2013\u2014\u2015\u00AD\u2018\u2019\u201A\u2032\u201C\u201D',
        E'---------\x27\x27\x27\x27""')
    ))),
    '[^a-z0-9]+', ' ', 'g'));
$$ LANGUAGE sql IMMUTABLE;
