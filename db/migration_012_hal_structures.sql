-- =============================================================
-- Migration 012 : Table de référence des structures HAL
-- =============================================================
-- Staging des structures HAL extraites des métadonnées de documents.
-- Sert de pont pour matcher hal_struct_id → structures locales.
-- =============================================================

BEGIN;

-- Supprimer hal_struct_id de structures si présent (migration 011 précédente)
ALTER TABLE structures DROP COLUMN IF EXISTS hal_struct_id;

CREATE TABLE IF NOT EXISTS hal_structures (
    hal_struct_id   INT PRIMARY KEY,
    name            TEXT NOT NULL,
    acronym         TEXT,
    type            TEXT,              -- 'laboratory', 'institution', 'regroupinstitution', ...
    parent_ids      INT[],             -- hal_struct_id des parents
    parent_names    TEXT[],
    -- Lien vers notre table structures (many hal_structures → one structure)
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,
    doc_count       INT DEFAULT 0,     -- nb de documents dans lesquels cette structure apparaît
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hal_struct_name ON hal_structures (lower(name));
CREATE INDEX IF NOT EXISTS idx_hal_struct_local ON hal_structures (structure_id)
    WHERE structure_id IS NOT NULL;

COMMIT;
