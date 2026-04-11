-- Stocker les métadonnées de publication sur source_documents pour découpler
-- la normalisation de la création de publications.
-- Chaque source a sa propre vue de ces métadonnées.

ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS journal_id INTEGER REFERENCES journals(id);
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS oa_status TEXT;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS language TEXT;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS container_title TEXT;
