-- Migration 002 : suppression de la colonne raw_orcid (openalex_authorships)
-- Redondante avec openalex_authors.orcid
-- 2026-04-04

ALTER TABLE openalex_authorships DROP COLUMN IF EXISTS raw_orcid;
