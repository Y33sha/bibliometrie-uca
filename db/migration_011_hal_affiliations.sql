-- =============================================================
-- Migration 011 : Affiliation auteur HAL propre
-- =============================================================
-- 1. hal_struct_id sur structures : identifiant numérique HAL de la structure
--    (permet de croiser avec authIdHasStructure_fs)
-- 2. hal_author_id sur publication_authors : identifiant numérique HAL de l'auteur
--    sur ce document (permet le lien auteur→structure par document)
-- 3. excluded sur publication_authors : pour marquer les liens auteur-publi
--    erronés (homonymes fusionnés à tort, etc.)
-- =============================================================

BEGIN;

-- 1. HAL author ID sur publication_authors
ALTER TABLE publication_authors ADD COLUMN IF NOT EXISTS hal_author_id INT;

-- 2. Exclusion manuelle
ALTER TABLE publication_authors ADD COLUMN IF NOT EXISTS excluded BOOLEAN DEFAULT FALSE;

-- Reset des is_uca_author HAL (ceux qui étaient marqués en masse)
UPDATE publication_authors
SET is_uca_author = FALSE,
    laboratory_id = NULL,
    affiliation_resolved_at = NULL
WHERE source = 'hal';

COMMIT;
