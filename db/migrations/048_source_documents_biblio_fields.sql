-- Stocker les métadonnées bibliographiques et enrichies sur source_documents
-- (données brutes par source, propagées vers publications lors de la création).
-- Et les colonnes correspondantes sur publications.

-- source_documents : données brutes par source
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS is_retracted BOOLEAN;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS abstract TEXT;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS keywords TEXT[];
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS topics JSONB;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS biblio JSONB;

-- publications : données canoniques (fusionnées depuis les sources)
-- is_retracted, volume, issue, first_page, last_page existent déjà (migration 046)
ALTER TABLE publications ADD COLUMN IF NOT EXISTS abstract TEXT;
ALTER TABLE publications ADD COLUMN IF NOT EXISTS keywords TEXT[];
ALTER TABLE publications ADD COLUMN IF NOT EXISTS topics JSONB;

-- Remplacer volume/issue/first_page/last_page par un seul champ jsonb
-- sur publications (migration 046 les avait ajoutés en colonnes séparées)
ALTER TABLE publications ADD COLUMN IF NOT EXISTS biblio JSONB;

-- Migrer les données existantes vers le champ jsonb
UPDATE publications SET biblio = jsonb_strip_nulls(jsonb_build_object(
    'volume', volume, 'issue', issue, 'first_page', first_page, 'last_page', last_page
)) WHERE volume IS NOT NULL OR issue IS NOT NULL OR first_page IS NOT NULL OR last_page IS NOT NULL;

ALTER TABLE publications DROP COLUMN IF EXISTS volume;
ALTER TABLE publications DROP COLUMN IF EXISTS issue;
ALTER TABLE publications DROP COLUMN IF EXISTS first_page;
ALTER TABLE publications DROP COLUMN IF EXISTS last_page;
