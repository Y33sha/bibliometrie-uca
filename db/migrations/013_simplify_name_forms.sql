-- Migration 013 : simplifier structure_name_forms
-- Supprimer is_regex, ne garder que la forme normalisée, contrainte d'unicité.
-- 2026-04-06

-- Supprimer la colonne regex
ALTER TABLE structure_name_forms DROP COLUMN IF EXISTS is_regex;

-- Remplacer form_text par la forme normalisée
UPDATE structure_name_forms SET form_text = form_normalized WHERE form_normalized IS NOT NULL;

-- Supprimer les doublons (garder celui avec le plus petit id)
DELETE FROM structure_name_forms
WHERE id NOT IN (
    SELECT MIN(id) FROM structure_name_forms GROUP BY structure_id, form_text
);

-- Supprimer form_normalized (maintenant identique à form_text)
ALTER TABLE structure_name_forms DROP COLUMN IF EXISTS form_normalized;

-- Contrainte d'unicité
ALTER TABLE structure_name_forms
    ADD CONSTRAINT uq_snf_structure_form UNIQUE (structure_id, form_text);
