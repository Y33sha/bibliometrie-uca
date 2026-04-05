-- Migration 004 : suppression des colonnes inutilisées de hal_structures
-- 2026-04-05

ALTER TABLE hal_structures
    DROP COLUMN IF EXISTS parent_names,
    DROP COLUMN IF EXISTS parent_acronyms,
    DROP COLUMN IF EXISTS parent_types,
    DROP COLUMN IF EXISTS alias_ids,
    DROP COLUMN IF EXISTS isni,
    DROP COLUMN IF EXISTS rnsr,
    DROP COLUMN IF EXISTS ror,
    DROP COLUMN IF EXISTS idref,
    DROP COLUMN IF EXISTS url,
    DROP COLUMN IF EXISTS address;

DROP INDEX IF EXISTS idx_hal_struct_alias_ids;
