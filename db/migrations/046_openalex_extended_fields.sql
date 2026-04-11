-- Colonnes supplémentaires pour exploiter les champs OpenAlex
-- (et préparées pour HAL/WoS à terme).

-- Publications : métadonnées bibliographiques et rétractation
ALTER TABLE publications ADD COLUMN IF NOT EXISTS is_retracted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE publications ADD COLUMN IF NOT EXISTS volume TEXT;
ALTER TABLE publications ADD COLUMN IF NOT EXISTS issue TEXT;
ALTER TABLE publications ADD COLUMN IF NOT EXISTS first_page TEXT;
ALTER TABLE publications ADD COLUMN IF NOT EXISTS last_page TEXT;

-- Source documents : URLs des versions disponibles et nombre de citations
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS urls TEXT[];
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS cited_by_count INTEGER;
