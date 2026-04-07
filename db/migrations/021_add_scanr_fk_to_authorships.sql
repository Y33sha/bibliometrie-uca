-- Ajouter la FK ScanR à la table authorships (table de vérité)
ALTER TABLE authorships
    ADD COLUMN IF NOT EXISTS scanr_authorship_id INTEGER
    REFERENCES scanr_authorships(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_authorships_scanr
    ON authorships (scanr_authorship_id)
    WHERE scanr_authorship_id IS NOT NULL;
