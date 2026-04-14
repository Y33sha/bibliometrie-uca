-- Migration 057: renomme collection(s) → hal_collections
-- et convertit staging.collection (text) en text[] pour cohérence.

-- source_documents : simple renommage
ALTER TABLE source_documents RENAME COLUMN collections TO hal_collections;
ALTER INDEX IF EXISTS idx_source_docs_collections RENAME TO idx_source_docs_hal_collections;

-- staging : renommage + conversion text → text[]
ALTER TABLE staging ADD COLUMN IF NOT EXISTS hal_collections text[];
UPDATE staging SET hal_collections = string_to_array(collection, ',')
    WHERE collection IS NOT NULL;
ALTER TABLE staging DROP COLUMN IF EXISTS collection;
