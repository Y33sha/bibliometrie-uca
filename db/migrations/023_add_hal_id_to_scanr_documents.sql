-- Migration 023 : Ajouter hal_id sur scanr_documents pour le dédoublonnage ScanR↔HAL
--
-- Le champ hal_id stocke l'identifiant HAL extrait des externalIds ScanR.
-- Il permet d'éviter la création de publications doublons quand un document
-- existe déjà dans HAL.

ALTER TABLE scanr_documents
    ADD COLUMN IF NOT EXISTS hal_id text;

CREATE INDEX IF NOT EXISTS idx_scanr_docs_hal_id
    ON scanr_documents (hal_id)
    WHERE hal_id IS NOT NULL;

-- Rétro-remplissage depuis les données brutes staging
UPDATE scanr_documents sd
SET hal_id = e.val
FROM staging_scanr ss,
     LATERAL (
         SELECT elem->>'id' AS val
         FROM jsonb_array_elements(ss.raw_data->'externalIds') elem
         WHERE elem->>'type' = 'hal'
         LIMIT 1
     ) e
WHERE sd.staging_id = ss.id
  AND sd.hal_id IS NULL;
