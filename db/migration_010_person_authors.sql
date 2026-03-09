-- =============================================================
-- Migration 010 : Lien persons ↔ authors
-- =============================================================
-- On met person_id sur authors (N auteurs → 1 personne)
-- plutôt que author_id sur persons.
-- =============================================================

BEGIN;

-- Ajouter person_id sur authors
ALTER TABLE authors ADD COLUMN IF NOT EXISTS person_id INT REFERENCES persons(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_authors_person ON authors (person_id) WHERE person_id IS NOT NULL;

-- Supprimer l'ancien author_id sur persons (jamais utilisé)
ALTER TABLE persons DROP COLUMN IF EXISTS author_id;
DROP INDEX IF EXISTS idx_persons_author;

COMMIT;
