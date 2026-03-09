-- Migration 005: flag auteurs identifiés UCA par OpenAlex
-- Usage: psql -d publisher-stats -f migration_005_oa_uca_flag.sql

BEGIN;

ALTER TABLE publication_authors
    ADD COLUMN IF NOT EXISTS is_uca_openalex BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_pa_uca_openalex
    ON publication_authors (is_uca_openalex) WHERE is_uca_openalex = TRUE;

COMMIT;
