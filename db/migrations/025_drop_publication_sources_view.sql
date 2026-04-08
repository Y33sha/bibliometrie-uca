-- Migration 025 : Suppression de la vue publication_sources
--
-- Remplacée par la colonne publications.sources (source_type[], GIN).
-- Plus aucun code applicatif ne l'utilise.

DROP VIEW IF EXISTS publication_sources;
