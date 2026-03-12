-- Migration 022 : Ajout de hal_form_id sur hal_authors
-- Permet de dédupliquer les auteurs sans compte HAL (personId = 0)
-- via leur identifiant de forme HAL (formId), extrait de authIdHasStructure_fs.

BEGIN;

ALTER TABLE hal_authors ADD COLUMN IF NOT EXISTS hal_form_id INTEGER;

-- Index unique partiel : un seul enregistrement par form_id (quand il est renseigné)
CREATE UNIQUE INDEX IF NOT EXISTS idx_hal_authors_form_id
    ON hal_authors (hal_form_id)
    WHERE hal_form_id IS NOT NULL;

COMMIT;
