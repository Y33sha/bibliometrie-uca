-- Migration 002: support pour la revue des faux positifs
-- Usage: psql -d publisher-stats -f migration_002_false_positives.sql

BEGIN;

-- Statut de vérification des publications
-- NULL = non vérifié, 'false_positive' = confirmé faux positif, 'valid_uca' = confirmé UCA
ALTER TABLE publications
    ADD COLUMN IF NOT EXISTS review_status TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_publications_review
    ON publications (review_status);

-- Table des formes confusantes (noms qui créent des faux positifs)
CREATE TABLE IF NOT EXISTS confusing_forms (
    id              SERIAL PRIMARY KEY,
    form            TEXT NOT NULL,               -- ex: "territoires", "blaise pascal"
    form_normalized TEXT NOT NULL,               -- minuscules, sans accents
    laboratory_id   INT REFERENCES laboratories(id), -- le labo UCA faussement identifié
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_confusing_forms_norm
    ON confusing_forms (form_normalized);

COMMIT;
