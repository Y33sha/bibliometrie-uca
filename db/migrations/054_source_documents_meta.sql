-- Migration 054: ajoute une colonne meta (jsonb) à source_documents
-- pour stocker les métadonnées spécifiques à la source (discipline, écoles
-- doctorales, partenaires de recherche, etc.) qui ne sont pas dans le schéma
-- relationnel mais qui étaient auparavant lues depuis staging.raw_data.
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS meta jsonb;
