-- Migration 010 : table wos_institutions (symétrie avec openalex_institutions)
-- 2026-04-05

CREATE TABLE IF NOT EXISTS wos_institutions (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    ror_id TEXT,
    country TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_wos_inst_ror ON wos_institutions (ror_id) WHERE ror_id IS NOT NULL;

-- Colonne wos_institution_ids sur wos_authorships (même pattern qu'openalex)
ALTER TABLE wos_authorships ADD COLUMN IF NOT EXISTS wos_institution_ids integer[];
