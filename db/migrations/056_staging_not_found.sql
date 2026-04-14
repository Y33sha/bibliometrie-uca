-- Migration 056: colonne not_found sur staging
--
-- Marque les documents dont l'identifiant source n'existe plus
-- (HAL-IDs fusionnés, documents supprimés, etc.).
-- Les cross-imports ignorent les documents marqués not_found.
ALTER TABLE staging ADD COLUMN IF NOT EXISTS not_found boolean DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_staging_not_found ON staging (source, source_id) WHERE not_found = TRUE;
