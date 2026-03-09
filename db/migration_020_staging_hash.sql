-- =============================================================
-- Migration 020 : ajout raw_hash aux tables de staging
-- =============================================================
-- Permet de détecter les modifications dans les sources (HAL, OpenAlex)
-- lors des extractions suivantes. Si le hash change, le document est
-- re-stagé (processed = FALSE) et sera re-normalisé.

ALTER TABLE staging_hal ADD COLUMN IF NOT EXISTS raw_hash TEXT;
ALTER TABLE staging_openalex ADD COLUMN IF NOT EXISTS raw_hash TEXT;

-- Calculer les hash pour les données existantes
UPDATE staging_hal SET raw_hash = md5(raw_data::text) WHERE raw_hash IS NULL;
UPDATE staging_openalex SET raw_hash = md5(raw_data::text) WHERE raw_hash IS NULL;
