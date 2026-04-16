-- Migration 004 : formes de noms excluantes + nettoyage colonnes inutiles

ALTER TABLE structure_name_forms DROP COLUMN IF EXISTS notes;
ALTER TABLE structure_name_forms DROP COLUMN IF EXISTS is_active;
ALTER TABLE structure_name_forms ADD COLUMN IF NOT EXISTS is_excluding boolean NOT NULL DEFAULT false;
