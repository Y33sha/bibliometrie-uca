-- Migration 053: supprime la colonne country (text, toujours NULL)
-- de la table addresses — remplacée par countries (text[]).
ALTER TABLE addresses DROP COLUMN IF EXISTS country;
