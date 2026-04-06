-- Migration 012 : flag word_boundary sur structure_name_forms
-- 2026-04-06

ALTER TABLE structure_name_forms ADD COLUMN IF NOT EXISTS is_word_boundary BOOLEAN NOT NULL DEFAULT FALSE;

-- Initialiser : formes de 6 chars ou moins → word_boundary par défaut
UPDATE structure_name_forms SET is_word_boundary = TRUE WHERE length(form_normalized) <= 6 AND NOT is_regex;
