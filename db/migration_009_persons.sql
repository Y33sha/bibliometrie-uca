-- =============================================================
-- Migration 009 : Table des personnes (données RH)
-- =============================================================
-- Personnes connues de l'UCA (enseignants-chercheurs, etc.)
-- Distincte de la table authors (qui vient des métadonnées de publis).
-- Le rapprochement persons ↔ authors se fera dans un second temps.
-- =============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS persons (
    id              SERIAL PRIMARY KEY,
    last_name       TEXT NOT NULL,
    first_name      TEXT NOT NULL,
    email           TEXT,
    -- Normalisation pour matching futur avec authors
    last_name_normalized  TEXT NOT NULL,
    first_name_normalized TEXT NOT NULL,
    -- Poste
    role_title      TEXT,             -- ex: 'PROF UNIV', 'MCF'
    -- Rattachement organisationnel (texte brut RH)
    department_name TEXT,             -- ex: 'LIMOS', 'UFR Lettres'
    -- Lien vers structure (rempli dans un second temps)
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,
    -- Période
    start_date      DATE,
    end_date        DATE,             -- NULL = toujours en poste
    -- Date de l'export RH ayant fourni cette donnée
    hr_export_date  DATE,
    -- Lien futur vers authors
    author_id       INT REFERENCES authors(id) ON DELETE SET NULL,
    -- Métadonnées
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_persons_name ON persons (last_name_normalized, first_name_normalized);
CREATE INDEX idx_persons_email ON persons (email) WHERE email IS NOT NULL;
CREATE INDEX idx_persons_structure ON persons (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX idx_persons_author ON persons (author_id) WHERE author_id IS NOT NULL;
CREATE INDEX idx_persons_department ON persons (department_name) WHERE department_name IS NOT NULL;

COMMIT;
