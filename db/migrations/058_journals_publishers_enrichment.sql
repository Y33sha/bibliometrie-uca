-- Migration 058 : enrichissement des tables journals et publishers
--
-- journals :
--   - journal_type : nature de l'objet (journal, proceedings, repository,
--     book_series, preprint_server, media)
--   - is_academic : distingue les sources académiques des médias grand public
--     (The Conversation, Science et Vie, etc.)
--   - doi_prefix : préfixe DOI du journal (ex: "10.1038/s41586") pour mapper
--     les publications par DOI et détecter les incohérences
--   - oa_model : renommage full_oa → gold/diamond selon le modèle
--
-- publishers :
--   - doi_prefix : préfixe DOI de l'éditeur (ex: "10.1038") pour regrouper
--     les journals d'un même éditeur et dédupliquer

-- Journals
ALTER TABLE journals ADD COLUMN IF NOT EXISTS journal_type text DEFAULT 'journal';
ALTER TABLE journals ADD COLUMN IF NOT EXISTS is_academic boolean DEFAULT TRUE;
ALTER TABLE journals ADD COLUMN IF NOT EXISTS doi_prefix text;

-- Publishers
ALTER TABLE publishers ADD COLUMN IF NOT EXISTS doi_prefix text;

-- Index sur doi_prefix pour les lookups
CREATE INDEX IF NOT EXISTS idx_journals_doi_prefix ON journals (doi_prefix) WHERE doi_prefix IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_publishers_doi_prefix ON publishers (doi_prefix) WHERE doi_prefix IS NOT NULL;

-- Marquer les repositories existants comme non-journals
UPDATE journals SET journal_type = 'repository' WHERE oa_model = 'repository';
