-- Migration 002 : supprimer colonnes inutiles de source_structures
-- enriched_at : plus d'enrichissement HAL séparé
-- acronym : non renseigné systématiquement, non utilisé

ALTER TABLE source_structures DROP COLUMN IF EXISTS enriched_at;
ALTER TABLE source_structures DROP COLUMN IF EXISTS acronym;
