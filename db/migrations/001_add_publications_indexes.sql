-- Migration 001 : index manquants sur publications
-- 2026-04-04

CREATE INDEX IF NOT EXISTS idx_publications_doi
    ON publications (lower(doi)) WHERE doi IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publications_year_type
    ON publications (pub_year, doc_type);
