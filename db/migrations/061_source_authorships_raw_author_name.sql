-- Migration 061: Ajouter raw_author_name sur source_authorships
--
-- Dénormalise le nom d'auteur (actuellement sur source_authors.full_name)
-- pour éviter les JOINs systématiques vers source_authors.
-- Le backfill est fait par processing/backfill_raw_author_name.py.

ALTER TABLE source_authorships ADD COLUMN IF NOT EXISTS raw_author_name text;
